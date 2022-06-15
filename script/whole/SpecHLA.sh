#!/bin/bash

###
### HLA typing with paired-end reads. This script can use PacBio, Nanopore,
### Hi-C, and 10X sequencing data to improve the phasing performance if provided.
### 
###
### Usage:
###   sh SpecHLA.sh -n <sample> -1 <sample.fq.1.gz> -2 <sample.fq.2.gz> -t <sample.pacbio.fq.gz> -p <Asian>
###
### Options:
###   -n        Sample ID. <required>
###   -1        The first fastq file. <required>
###   -2        The second fastq file. <required>
###   -o        The output folder to store the typing results.
###   -u        Choose full-length or exon typing. 0 indicates full-length, 1 means exon, 
###             default is to perform full-length typing.
###   -t        Pacbio TGS fastq file.
###   -e        Nanopore TGS fastq file.
###   -x        Path of folder created by 10x demultiplexing. Prefix of the filenames of FASTQs
###             should be the same as Sample ID. You can regard reads as normal NGS reads and use 
###             this parameter to adopt barcode information to improve phasing.
###   -c        fwd hi-c fastq file.
###   -d        rev hi-c fastq file.
###   -w        The weight of using phase information of allele imbalance [0-1], default is 0.
###   -p        The population of the sample [ Asian, Black, Caucasian, nonuse]. Use mean frequency
###             if not provided. nonuse indicates only adopting mapping score to annotate the allele. 
###   -j        Number of threads [5]
###   -m        The maximum mismatch number tolerated in assigning gene-specific reads. Deault
###             is 2. It should be set larger to infer novel alleles.
###   -v        True or False. Consider long InDels if True, else only consider short variants. 
###             Default is False.
###   -q        Minimum variant quality. Default is 0.01. Set it larger in high quality samples.
###   -s        Minimum mapping depth of variant. Default is 5.
###   -a        Use this long InDel file if provided.
###   -r        The minimum Minor Allele Frequency (MAF), default is 0.05 for whole gene and
###             0.1 for exon typing.
###   -h        Show this message.

help() {
    sed -rn 's/^### ?//;T;p' "$0"
}

if [[ $# == 0 ]] || [[ "$1" == "-h" ]]; then
    help
    exit 1
fi

while getopts ":n:1:2:p:f:m:v:q:t:a:e:x:c:d:r:y:o:j:w:u:s:" opt; do
  case $opt in
    n) sample="$OPTARG"
    ;;
    1) fq1="$OPTARG"
    ;;
    2) fq2="$OPTARG"
    ;;
    p) pop="$OPTARG"
    ;;
    m) nm="$OPTARG"
    ;;
    v) long_indel="$OPTARG"
    ;;
    q) snp_quality="$OPTARG"
    ;;
    t) tgs="$OPTARG"
    ;;
    a) sv="$OPTARG"
    ;;
    e) nanopore_data="$OPTARG"
    ;;
    x) tenx_data="$OPTARG"
    ;;
    c) hic_data_fwd="$OPTARG"
    ;;
    d) hic_data_rev="$OPTARG"
    ;;
    r) maf="$OPTARG"
    ;;
    o) given_outdir="$OPTARG"
    ;;
    j) num_threads="$OPTARG"
    ;;
    w) weight_imb="$OPTARG"
    ;;
    u) focus_exon="$OPTARG"
    ;;
    s) snp_dp="$OPTARG"
    ;;
    \?) echo "Invalid option -$OPTARG" >&2
    ;;
  esac
done


dir=$(cd `dirname $0`; pwd)
export LD_LIBRARY_PATH=$dir/../../spechla_env/lib
bin=$dir/../../bin
db=$dir/../../db
hlaref=$db/ref/hla.ref.extend.fa

if [ ${given_outdir:-NA} == NA ]
  then
    outdir=$(pwd)/output/$sample
  else
    outdir=$given_outdir/$sample   
fi
focus_exon_flag=${focus_exon:-0} # default is perform full-length typing

echo Start profiling HLA for $sample. 
mkdir -p $outdir
# exec >$outdir/$sample.log 2>&1 #redirect log info to the outdir
group='@RG\tID:'$sample'\tSM:'$sample
echo use ${num_threads:-5} threads.

# :<<!
# ################ remove the repeat read name #################
python3 $dir/../uniq_read_name.py $fq1 $outdir/$sample.uniq.name.R1.gz
python3 $dir/../uniq_read_name.py $fq2 $outdir/$sample.uniq.name.R2.gz
fq1=$outdir/$sample.uniq.name.R1.gz
fq2=$outdir/$sample.uniq.name.R2.gz
# ###############################################################



# ################### assign the reads to original gene######################################################
echo map the reads to database to assign reads to corresponding genes.
license=$dir/../../bin/novoalign.lic
if [ $focus_exon_flag == 1 ];then
  database_prefix=hla_gen.format.filter.extend.DRB.no26789
else
  database_prefix=hla_gen.format.filter.extend.DRB.no26789.v2
fi
if [ -f "$license" ];then
    $bin/novoalign -d $db/ref/$database_prefix.ndx -f $fq1 $fq2 -F STDFQ -o SAM \
    -o FullNW -r All 100000 --mCPU ${num_threads:-5} -c 10  -g 20 -x 3  | $bin/samtools view \
    -Sb - | $bin/samtools sort -  > $outdir/$sample.map_database.bam
else
    $bin/bowtie2/bowtie2 -p ${num_threads:-5} -k 10 -x $db/ref/$database_prefix.fasta -1 $fq1 -2 $fq2|\
    $bin/samtools view -bS -| $bin/samtools sort - >$outdir/$sample.map_database.bam
fi
$bin/samtools index $outdir/$sample.map_database.bam

python3 $dir/../assign_reads_to_genes.py -1 $fq1 -2 $fq2 -n $bin -o $outdir \
-b ${outdir}/${sample}.map_database.bam -nm ${nm:-2}
# #############################################################################################################



# ########### align the gene-specific reads to the corresponding gene reference################################
$bin/bwa mem -U 10000 -L 10000,10000 -R $group $hlaref $fq1 $fq2 | $bin/samtools view -H  >$outdir/header.sam
#hlas=(A B C)
hlas=(A B C DPA1 DPB1 DQA1 DQB1 DRB1)
for hla in ${hlas[@]}; do
        hla_ref=$db/HLA/HLA_$hla/HLA_$hla.fa
        $bin/bwa mem -t ${num_threads:-5} -U 10000 -L 10000,10000 -R $group $hla_ref $outdir/$hla.R1.fq.gz $outdir/$hla.R2.fq.gz\
         | $bin/samtools view -bS -F 0x800 -| $bin/samtools sort - >$outdir/$hla.bam
        $bin/samtools index $outdir/$hla.bam
done
$bin/samtools merge -f -h $outdir/header.sam $outdir/$sample.merge.bam $outdir/A.bam $outdir/B.bam $outdir/C.bam\
 $outdir/DPA1.bam $outdir/DPB1.bam $outdir/DQA1.bam $outdir/DQB1.bam $outdir/DRB1.bam
$bin/samtools index $outdir/$sample.merge.bam
# ###############################################################################################################


# ################################### local assembly and realignment #################################
echo start realignment.
if [ $focus_exon_flag == 1 ];then #exon
  assemble_region=$dir/select.region.exon.txt
else # full length
  assemble_region=$dir/select.region.txt
fi
sh $dir/../run.assembly.realign.sh $sample $outdir/$sample.merge.bam $outdir 70 $assemble_region ${num_threads:-5}
$bin/freebayes -a -f $hlaref -p 3 $outdir/$sample.realign.sort.bam > $outdir/$sample.realign.vcf && \
rm -rf $outdir/$sample.realign.vcf.gz 
bgzip -f $outdir/$sample.realign.vcf
tabix -f $outdir/$sample.realign.vcf.gz
less $outdir/$sample.realign.vcf.gz |grep "#" > $outdir/$sample.realign.filter.vcf

if [ $focus_exon_flag == 1 ];then #exon
    $bin/bcftools filter -R $dir/exon_extent.bed $outdir/$sample.realign.vcf.gz |grep -v "#"  >> $outdir/$sample.realign.filter.vcf  
else # full length
    $bin/bcftools filter -t HLA_A:1000-4503,HLA_B:1000-5081,HLA_C:1000-5304,HLA_DPA1:1000-10775,HLA_DPB1:1000-12468,\
    HLA_DQA1:1000-7492,HLA_DQB1:1000-8480,HLA_DRB1:1000-12229 $outdir/$sample.realign.vcf.gz |grep -v "#" \
    >> $outdir/$sample.realign.filter.vcf  
fi
# #####################################################################################################


!

# ###################### call long indel #############################################
bam=$outdir/$sample.realign.sort.bam
vcf=$outdir/$sample.realign.filter.vcf

if [ ${long_indel:-False} == True ] && [ $focus_exon_flag != 1 ]; #don't call long indel for exon typing
  then
  port=$(date +%N|cut -c5-9)
  sh $dir/../ScanIndel/run_scanindel_sample.sh $sample $bam $outdir $port
  bfile=$outdir/Scanindel/$sample.breakpoint.txt
  if [ ${tgs:-NA} != NA ]
    then
    $bin/pbmm2 align $hlaref ${tgs:-NA} $outdir/$sample.movie1.bam --sort --preset HIFI --sample $sample --rg '@RG\tID:movie1'
    $bin/pbsv discover $outdir/$sample.movie1.bam $outdir/$sample.svsig.gz
    $bin/pbsv call $hlaref $outdir/$sample.svsig.gz $outdir/$sample.var.vcf
    python3 $dir/vcf2bp.py $outdir/$sample.var.vcf $outdir/$sample.tgs.breakpoint.txt
    cat $outdir/$sample.tgs.breakpoint.txt >>$bfile
  fi
else
  bfile=nothing
fi
if [ ${sv:-NA} != NA ]
  then
  bfile=$sv
fi
# #############################################################################################


# ########### phase, link blocks, calculate haplotype ratio, give typing results ##############
if [ "$maf" == "" ];then
    if [ $focus_exon_flag != 1 ]; then
        my_maf=0.05
    else
        my_maf=0.1
    fi
else
    my_maf=$maf
fi

echo Minimum Minor Allele Frequency is $my_maf.
# hlas=(B)
hlas=(A B C DPA1 DPB1 DQA1 DQB1 DRB1)
for hla in ${hlas[@]}; do
hla_ref=$db/ref/HLA_$hla.fa
python3 $dir/../phase_variants.py \
  -o $outdir \
  -b $bam \
  -s $bfile \
  -v $vcf \
  --fq1 $outdir/$hla.R1.fq.gz \
  --fq2 $outdir/$hla.R2.fq.gz \
  --gene HLA_$hla \
  --freq_bias $my_maf \
  --snp_qual ${snp_quality:-0.01} \
  --snp_dp ${snp_dp:-5} \
  --ref $hla_ref \
  --tgs ${tgs:-NA} \
  --nanopore ${nanopore_data:-NA} \
  --hic_fwd ${hic_data_fwd:-NA} \
  --hic_rev ${hic_data_rev:-NA} \
  --tenx ${tenx_data:-NA} \
  --sa $sample \
  --weight_imb ${weight_imb:-0} \
  --exon $focus_exon_flag 
done
# ##################################################################################################

!

# ############################ annotation ####################################
echo start annotation...
# perl $dir/annoHLApop.pl $sample $outdir $outdir 2 $pop
if [ $focus_exon_flag == 1 ];then #exon
    perl $dir/annoHLA.pl -s $sample -i $outdir -p ${pop:-Unknown} -r exon
else
    perl $dir/annoHLA.pl -s $sample -i $outdir -p ${pop:-Unknown} -r whole
fi
# #############################################################################



# sh $dir/../clear_output.sh $outdir/
cat $outdir/hla.result.txt
echo $sample is done.
