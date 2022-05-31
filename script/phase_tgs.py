#!/usr/bin/env python3
from argparse import ArgumentParser
from argparse import ArgumentTypeError
from my_imports import *
import time
import re
from itertools import combinations, permutations
import realign_and_sv_break

def str2bool(v):
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise ArgumentTypeError('Please give right flag (True or False).')

Usage = \
"""
python3 phase_tgs.py [options] 

Help information can be found by python3 phase_tgs.py -h/--help, additional information can be found in \
README.MD or https://github.com/deepomicslab/SpecHLA.
"""
scripts_dir=sys.path[0]+'/'
parser = ArgumentParser(description="SpecHLA.",prog='python3 phase_tgs.py',usage=Usage)
optional=parser._action_groups.pop()
required=parser.add_argument_group('required arguments')
flag_parser = parser.add_mutually_exclusive_group(required=False)
flag_data = parser.add_mutually_exclusive_group(required=False)
#necessary parameter
required.add_argument("--ref",help="The hla reference file used in alignment",dest='ref',metavar='', type=str)
required.add_argument("-b", "--bam",help="The bam file of the input samples.",dest='bamfile',metavar='')
required.add_argument("-v", "--vcf",help="The vcf file of the input samples.",dest='vcf',metavar='')
required.add_argument("--sa",help="Sample ID",dest='sample_id',metavar='', type=str)
required.add_argument("-s", "--sv",help="Long Indel file after scanindel, we will not consider long InDel \
    if not afforded.",dest='sv',metavar='')
required.add_argument("--gene",help="gene",dest='gene',metavar='', type=str)
required.add_argument("--fq1",help="fq1",dest='fq1',metavar='', type=str)
required.add_argument("--fq2",help="fq2",dest='fq2',metavar='', type=str)
required.add_argument("--tgs",help="PACBIO TGS fastq",dest='tgs',metavar='', type=str)
required.add_argument("--nanopore",help="NANOPORE TGS fastq",dest='nanopore',metavar='', type=str)
required.add_argument("--hic_fwd",help="fwd_hic.fastq",dest='hic_fwd',metavar='', type=str)
required.add_argument("--hic_rev",help="rev_hic.fastq",dest='hic_rev',metavar='', type=str)
required.add_argument("--tenx",help="10X data",dest='tenx',metavar='', type=str)
required.add_argument("-o", "--outdir",help="The output directory.",dest='outdir',metavar='')
optional.add_argument("--freq_bias",help="freq_bias (default is 0.05)",dest='freq_bias',\
    metavar='',default=0.05, type=float)
optional.add_argument("--snp_dp",help="The minimum depth of SNPs to be considered in HLAtyping\
     step (default is 5).",dest='snp_dp',metavar='',default=5, type=int)
optional.add_argument("--snp_qual",help="The minimum quality of SNPs to be considered in HLAtyping\
     step (default is 0.01).",dest='snp_qual',metavar='',default=0.01, type=float)
optional.add_argument("--indel_len",help="The maximum length for indel to be considered in HLAtyping\
     step (default is 150).",dest='indel_len',metavar='',default=150, type=int)
optional.add_argument("--block_len",help="The minimum length for block to be considered in final\
     result (default is 300).",dest='block_len',metavar='',default=300, type=int)
optional.add_argument("--points_num",help="The minimum hete loci number for block to be considered\
     in final result (default is 2).",dest='points_num',metavar='',default=2, type=int)
optional.add_argument("--weight_imb",help="The weight of using phase information of allele imbalance\
 [0-1], default is 0. (default is 0)",dest='weight_imb',metavar='',default=0, type=float)
optional.add_argument("--reads_num",help="The number of supporting reads between two adjcent loci\
     lower than this value will be regard as break points.(default is 10)",dest='reads_num',\
     metavar='',default=10, type=int)
optional.add_argument("--noise_num",help="If the haplotype number is 2, there will be at most two \
    types of linked reads. If the third type of reads number is over this value, then these two \
    loci will be regarded as break points.(default is 5)",dest='noise_num',metavar='',default=5, \
    type=int)

parser._action_groups.append(optional)
args = parser.parse_args()

def if_in_deletion(locus, deletion_region):
    dele_flag = False
    for deletion in deletion_region:
        if locus >= deletion[0] and locus < deletion[1]:
            dele_flag = True
    return dele_flag

def read_spechap_seq(vcf, snp_list):
    snp_locus_list = []
    for snp in snp_list:
        snp_locus_list.append(int(snp[1]))
    
    seq_list = [[],[]]
    in_vcf = VariantFile(vcf)
    sample = list(in_vcf.header.samples)[0]
    for record in in_vcf.fetch():
        geno = record.samples[sample]['GT']
        #print (record)
        # if geno == (1,1):
        #     continue
        if record.pos not in snp_locus_list:
            continue
        if sum(geno) == 1 or sum(geno) == 0:
            for i in range(2):
                seq_list[i].append(geno[i])
        else: 
            # print (record, geno)
            for i in range(2):
                seq_list[i].append(geno[i] - 1)

    return seq_list 

def read_vcf(vcffile,outdir,snp_dp,bamfile,indel_len,gene,freq_bias,strainsNum,deletion_region,snp_qual,gene_vcf):
    snp_index = 1
    snp_index_dict = {}
    pysam.index(bamfile)
    samfile = pysam.AlignmentFile(bamfile, "rb")
    if not os.path.exists(outdir):
        os.system('mkdir '+outdir)
    in_vcf = VariantFile(vcffile) # convert vcf to double-allele vcf
    md_vcf = VariantFile(gene_vcf,'w',header=in_vcf.header)
    sample = list(in_vcf.header.samples)[0]
    snp_list, beta_set, allele_set = [], [], []
    for record in in_vcf.fetch():
        if 'DP' not in record.info.keys() or record.info['DP'] <1:
            continue
        geno = record.samples[sample]['GT']    
        depth = record.samples[sample]['AD']
        dp=sum(depth)  
        if record.qual == None:
            print ('WARNING: no vcf quality value.')
            continue
        if record.qual < snp_qual:
            continue
        if record.chrom != gene:
            continue
        if record.chrom == 'HLA_DRB1' and record.pos >= 3898 and record.pos <= 4400:
            continue
        if dp < snp_dp:
            continue
        if geno == (0,1,2):
            continue
        if len(record.ref) > indel_len:
            continue
        if len(record.alts) > 2:
            continue
        alt_too_long = False
        for alt_allele in record.alts:
            if len(alt_allele) > indel_len:
                alt_too_long = True
        if alt_too_long:
            continue


        snp_index_dict[record.pos] = snp_index
        snp_index += 1

        # if the variant is in deletion region, get consensus haplotype
        if if_in_deletion(record.pos, deletion_region) and geno != (1,1,1):
            if geno == (1,1,2) or geno == (1,2,2):                
                snp = [record.chrom,record.pos,record.alts[0],record.alts[1],record.ref]
            else:
                snp=[record.chrom,record.pos,record.ref,record.alts[0],record.ref]

            reads_list = reads_support(samfile, snp)
            allele_dp = [len(reads_list[0]), len(reads_list[1])]
            new_dp=sum(allele_dp)
            if new_dp == 0:
                print ('WARNING: the depth of the locus obtained by pysam is zero!',snp)
                continue
            beta=float(allele_dp[1])/new_dp

            if beta <= 1-beta:
                if geno == (1,1,2) or geno == (1,2,2):
                    record.samples[sample]['GT']= tuple([1,1])
                else:
                    record.samples[sample]['GT']= tuple([0,0])
                record.samples[sample].phased=True
            elif beta >= 1 - beta:
                if geno == (1,1,2) or geno == (1,2,2):
                    record.samples[sample]['GT']= tuple([2,2]) 
                else:
                    record.samples[sample]['GT']= tuple([1,1])
                record.samples[sample].phased=True
            md_vcf.write(record)
            continue

        if geno == (1,1,1):
            record.samples[sample]['GT']= tuple([1,1])
            record.samples[sample].phased=True
        else:
            if geno == (1,1,2) or geno == (1,2,2):                
                snp = [record.chrom,record.pos,record.alts[0],record.alts[1],record.ref]
            else:
                snp=[record.chrom,record.pos,record.ref,record.alts[0],record.ref]

            reads_list = reads_support(samfile, snp)
            allele_dp = [len(reads_list[0]), len(reads_list[1])]
            new_dp = sum(allele_dp)
            # print (record, allele_dp)
            if new_dp == 0:
                print ('WARNING: the depth of the locus obtained by pysam is zero!',snp)
                continue
            beta = float(allele_dp[1])/new_dp # the frequency of alt

            if beta <= freq_bias:
                if geno == (1,1,2) or geno == (1,2,2):
                    record.samples[sample]['GT']= tuple([1,1])
                else:
                    record.samples[sample]['GT']= tuple([0,0])
                record.samples[sample].phased=True
            elif beta >= 1 - freq_bias:
                if geno == (1,1,2) or geno == (1,2,2):
                    record.samples[sample]['GT']= tuple([2,2]) 
                else:
                    record.samples[sample]['GT']= tuple([1,1])
                record.samples[sample].phased=True
            else:
                # each locus has 3 alleles, because freebayes -p 3
                # convert the variant to double allele variant.
                if geno == (1,1,2) or geno == (1,2,2):
                    record.samples[sample]['GT']= tuple([1,2])
                else:
                    record.samples[sample]['GT']= tuple([0,1])
                snp_list.append(snp)
                allele_dp = np.array(allele_dp)
                beta_set.append(allele_dp/new_dp)
        # print ("new", record.samples[sample]['GT'])
        md_vcf.write(record)
    in_vcf.close()
    md_vcf.close()
    os.system('tabix -f %s'%(gene_vcf))
    print ("The number of short hete loci is %s."%(len(snp_list)))
    return snp_list, beta_set, snp_index_dict

def freq_output(outdir, gene, fresh_alpha):
    ra_file=open(outdir+'/%s_freq.txt'%(gene),'w')    
    print ('# HLA\tFrequency',file=ra_file)
    for j in range(len(fresh_alpha)):
        print ('str-'+str(j+1),fresh_alpha[j],file=ra_file)
    ra_file.close()
        
def isfloat(x):
    try:
        float(x)
        return True
    except ValueError:
        return False

def reads_support(samfile,first):   
    reads_list=[]
    allele_num=len(first[3])+1
    for i in range(allele_num):
        reads_list.append([])
    num=0
    for read in samfile.fetch(str(first[0]),int(first[1])-1,int(first[1])):
        
        if int(first[1])-1 in read.get_reference_positions(full_length=True) and read.mapping_quality >1:   
            
            reads_index=read.get_reference_positions(full_length=True).index(int(first[1])-1)
            if first[2][0] != first[3][0]:
                #if the first allele is not same for indel alleles, we can just focus on the first locus 
                if read.query_sequence[reads_index] == first[2][0]:
                    reads_list[0].append(read.query_name)
                elif read.query_sequence[reads_index] == first[3][0]:
                    reads_list[1].append(read.query_name)
            else:  
                index_list=[]
                true_ref=first[4]
                for i in range(len(true_ref)):
                #for i in range(len(first[3])):
                    position=first[1]+i
                    point_flag=isin(position-1,read.get_reference_positions(full_length=True))
                    if point_flag:
                        position_index=read.get_reference_positions(full_length=True).index(position-1)
                        index_list.append(position_index)
                allele_list=read.query_sequence[index_list[0]:index_list[-1]+1].upper()
                ##########for the case that ref is short than alt.#########
                if index_list[-1]+1 < len(read.get_reference_positions(full_length=True)) and len(true_ref) < len(first[2])\
                     and len(true_ref) < len(first[3]) and read.get_reference_positions(full_length=True)[index_list[-1]+1] == None:
                    j = 0
                    # print ('#####', first, allele_list)
                    while index_list[-1]+1+j <  len(read.get_reference_positions(full_length=True)):
                        tag = read.get_reference_positions(full_length=True)[index_list[-1]+1+j]
                        # print (first, tag, type(tag))
                        if read.get_reference_positions(full_length=True)[index_list[-1]+1+j] == None:
                            allele_list+=read.query_sequence[index_list[-1]+1+j]
                        else:
                            break
                        j += 1   
                    # print (first, allele_list)
                ##########for the case that ref is short than alt.#########             
                if allele_list == first[2]:
                    reads_list[0].append(read.query_name)
                elif allele_list == first[3]:
                    reads_list[1].append(read.query_name)
    return reads_list

def link_reads(samfile,left,right,new_left,snp_index_dict,f):
    left_reads=new_left
    right_reads=reads_support(samfile,right)
    delta_count=[]
    for i in range(2):
        for j in range(2):
            left_set=left_reads[i]
            right_set=right_reads[j]
            reads_name = set(left_set).intersection(set(right_set))
            for name in reads_name:
                if len(left[2]) > 1 or len(left[3]) > 1 or len(right[2]) > 1 or len(right[3]) > 1:
                    left_index = snp_index_dict[int(left[1])]
                    right_index = snp_index_dict[int(right[1])]
                    left_geno = i
                    right_geno = j
                    if new_formate:
                        print('2 %s 1 -1 -1 %s %s %s %s II 60'%(name, left_index, left_geno, right_index, right_geno), file=f)
                    else:
                        print('2 %s %s %s %s %s II 60'%(name, left_index, left_geno, right_index, right_geno), file=f)
            same_num=len(reads_name)
            delta_count.append(same_num)
    return delta_count,right_reads

def extract_linkage_for_indel(bamfile,snp_list,snp_index_dict,outdir):
    # ExtractHAIR may loss some linkage info for indel
    # read bam and find the linkage for indels.
    f = open(outdir + '/fragment.add.file', 'w')
    samfile = pysam.AlignmentFile(bamfile, "rb")
    new_left=''
    for i in range(len(snp_list)-1):  
        left=snp_list[i]
        right=snp_list[i+1]  
        if new_left=='':   
            new_left=reads_support(samfile,left)
        delta_count,right_reads=link_reads(samfile,left,right,new_left,snp_index_dict, f)
        new_left=right_reads
    f.close()

def isin(x,seq):
    try:
        seq.index(x)
        return True
    except :
        return False

def block_phase(outdir,seq_list,snp_list,gene,gene_vcf,rephase_vcf):
    file=outdir+'/%s_break_points_phased.txt'%(gene)
    record_block_haps = []
    if os.path.isfile(file) and os.path.getsize(file):
        for line in open(file,'r'):
            if line[0] == '#':
                continue
            line=line.strip()
            array=line.split()
            gene_name=array[0]
            if gene_name != gene:
                print ("wrong gene!", gene_name, gene)
            start = int(array[1])
            end = int(array[2])
            genotype = int(array[3])
            record_block_haps.append([start, end, genotype])

    seq=np.array(seq_list)
    seq=np.transpose(seq)
    snp=snp_list  
    update_seqlist=[]

    he=0
    m = VariantFile(gene_vcf)
    
    if os.path.isfile(rephase_vcf):
        os.system('rm %s'%(rephase_vcf))
    out = VariantFile(rephase_vcf,'w',header=m.header)
    sample = list(m.header.samples)[0]
    for record in m.fetch():
        geno = record.samples[sample]['GT']    
        depth = record.samples[sample]['AD']
        if geno != (0,0) and geno != (1,1) and geno != (2,2):
            if geno == (1,2) or geno == (2,1):
                phased_locus = seq[he]
                for i in range(len(phased_locus)):
                    phased_locus[i] += 1
            else:
                phased_locus=seq[he]

            # check if it needs to reverse the genotype of the locus
            ref_order = [0, 1]
            for block in record_block_haps:
                if record.pos >= block[0] and record.pos <= block[1]:
                    if block[2] == 1:
                        ref_order = [1, 0]
                    break
            update_phased_locus=[]
            for pp in range(2):
                update_phased_locus.append(phased_locus[int(ref_order[pp])])
            phased_locus=update_phased_locus[:]
            # print (record, phased_locus)
            record.samples[sample]['GT']= tuple(phased_locus)
            record.samples[sample].phased=True

            if phased_locus[0] > 1 or phased_locus[1]>1:
                phased_locus[0]-=1
                phased_locus[1]-=1
            update_seqlist.append(phased_locus)
            he+=1
        out.write(record)
    m.close()
    out.close()
    os.system('tabix -f %s'%(rephase_vcf))
    return update_seqlist

def gene_phased(update_seqlist,snp_list, gene):
    gene_profile={}
    # gene_name=['HLA_A','HLA_B','HLA_C','HLA_DQB1','HLA_DRB1','HLA_DQA1','HLA_DPA1','HLA_DPB1']
    # for gene in gene_name:
    gene_snp=[]
    gene_seq=[]
    for i in range(len(snp_list)):
        if snp_list[i][0] == gene:
            gene_snp.append(snp_list[i])
            gene_seq.append(update_seqlist[i])
    gene_seq = np.array(gene_seq) 
    gene_seq = np.transpose(gene_seq)
    gene_profile[gene] = [gene_snp,gene_seq]
    return gene_profile

def no_snv_gene_phased(gene_vcf, outdir, gene, strainsNum):
    in_vcf = VariantFile(gene_vcf)
    out_vcf = VariantFile('%s/%s.rephase.vcf.gz'%(outdir, gene),'w',header=in_vcf.header)
    sample = list(in_vcf.header.samples)[0]
    for record in in_vcf.fetch():
        if record.chrom == gene and record.samples[sample]['GT'] == (1, 1, 1):
            # print (gene, record)
            phased_locus=[1] * strainsNum
            record.samples[sample]['GT']= tuple(phased_locus)
            record.samples[sample].phased=True
            out_vcf.write(record)
    in_vcf.close()
    out_vcf.close()
    os.system('tabix -f %s/%s.rephase.vcf.gz'%(outdir,gene))
    ra_file=open(outdir+'/%s_freq.txt'%(gene),'w')    
    print ('# HLA\tFrequency',file=ra_file)
    print ('str-'+str(1), 1, file=ra_file)
    for j in range(1, strainsNum):
        print ('str-'+str(j+1), 0, file=ra_file)
    ra_file.close()

    ####
    gene_profile={}
    gene_name=['HLA_A','HLA_B','HLA_C','HLA_DQB1','HLA_DRB1','HLA_DQA1','HLA_DPA1','HLA_DPB1']
    for gene in gene_name:
        gene_snp=[]
        gene_seq=[]
        gene_profile[gene] = [gene_snp,gene_seq]
    return gene_profile

def read_dup():
    dup_dict={}
    for line in open(sys.path[0]+'/complex_region.txt','r'):
        line=line.strip()
        array=line.split()
        dup_dict[array[0]]=array[1:]
    return dup_dict

########align the segs from SV haps result
def isOut(index, myset):
    if index < len(myset):
        return myset[index]
    else:
        return 'NA'

def exists_index(seg_set):
    exists_dict = {}
    for i in range(len(seg_set)):
        for j in range(1000):
            if isOut(j, seg_set[i]) != 'NA':
                if seg_set[i][j] not in exists_dict.keys():
                    exists_dict[seg_set[i][j]] = [j]
                else:
                    exists_dict[seg_set[i][j]].append(j)
    for key in exists_dict.keys():
        exists_dict[key] = sorted(exists_dict[key])
    #to ensure the following segs index is larger than previous segs
    newflag = True
    while newflag:
        newflag = False
        for i in range(len(seg_set)):
            for j in range(1000):
                if isOut(j, seg_set[i]) != 'NA' and isOut(j+1, seg_set[i]) != 'NA':
                    if max(exists_dict[seg_set[i][j+1]]) <= max(exists_dict[seg_set[i][j]]) or\
                        min(exists_dict[seg_set[i][j+1]]) <= min(exists_dict[seg_set[i][j]]) :
                            newflag = True
                            for w in range(len(exists_dict[seg_set[i][j+1]])):
                                exists_dict[seg_set[i][j+1]][w] = exists_dict[seg_set[i][j+1]][w] + 1
    return exists_dict

def focus_region():
    return {'HLA_A':[1000,4503],'HLA_B':[1000,5081],'HLA_C':[1000,5304],'HLA_DPA1':[1000,10775],\
        'HLA_DPB1':[1000,12468],'HLA_DQA1':[1000,7492],'HLA_DQB1':[1000,8480],'HLA_DRB1':[1000,12229]}

class Share_reads():

    def __init__(self, deletion_region, outdir, strainsNum, gene, gene_profile, ins_seq):
        self.deletion_region = deletion_region
        print ('initial', self.deletion_region)
        self.bamfile = outdir + '/newref_insertion.bam'
        self.vcf = outdir + '/%s.insertion.phased.vcf.gz'%(gene)
        self.strainsNum = strainsNum
        self.gene = gene
        self.normal_sequence=gene_profile[self.gene]
        self.reads_support = self.normal_reads()
        self.outdir = outdir
        self.ins_seq = ins_seq
        self.dup_file = outdir +'/select.DRB1.seq.txt'
        
    def generate_normal_region(self):
        gene_area = focus_region()[self.gene]
        normal_region = []
        segs = []
        gene_area[0] = int(float(gene_area[0])) + 1
        gene_area[1] = int(float(gene_area[1]))
        start = gene_area[0]
        for i in range(len(self.deletion_region)):
            if self.deletion_region[i][1] > gene_area[1]:
                self.deletion_region[i][1] = gene_area[1]
            if start < self.deletion_region[i][0]:
                segs.append([start, self.deletion_region[i][0] - 1, 'normal', '.'])
            if self.deletion_region[i][0] == self.deletion_region[i][1]:
                segs.append([self.deletion_region[i][0], self.deletion_region[i][1], 'insertion', i])
                # continue
            else:
                segs.append([self.deletion_region[i][0], self.deletion_region[i][1], 'deletion', i])
            normal_region.append([start, self.deletion_region[i][0]])
            start = self.deletion_region[i][1] + 1
        if int(start) < gene_area[1]:
            normal_region.append([start, gene_area[1]])
            segs.append([start, gene_area[1], 'normal', '.'])
        return normal_region, segs

    def normal_reads(self):
        normal_region, segs = self.generate_normal_region()
        reads_support = []
        for i in range(self.strainsNum):
            reads_support.append([])
        samfile = pysam.AlignmentFile(self.bamfile, "rb")
        for region in normal_region:
            if abs(region[0] - region[1]) < 10:
                continue
            for read in samfile.fetch(self.gene, region[0] - 1, region[1]):
                rivet_points=False
                support_alleles=[]
                support_loci=[]
                for i in range(len(self.normal_sequence[0])):
                    snv=self.normal_sequence[0][i]
                    if len(snv[2]) != 1 or len(snv[3]) != 1:
                        continue
                    if int(snv[1])-1 in read.get_reference_positions(full_length=True):
                        reads_index=read.get_reference_positions(full_length=True).index(int(snv[1])-1)
                        support_alleles.append(read.query_sequence[reads_index])
                        # print (read.query_name,snv,support_alleles)
                        rivet_points=True
                        support_loci.append(i)
                if rivet_points==True:
                    #if the reads has information, check which hap it belongs to.
                    hap_belong=self.check_hap(support_alleles,support_loci)[0]
                    if hap_belong != 'NA':
                        reads_support[hap_belong].append(read.query_name)
        return reads_support

    def check_hap(self,support_alleles,support_loci):
        support_num=[]  #check the allele num that support the each hap respectively.
        for i in range(self.strainsNum):
            support_num.append(0)
        for i in range(len(support_loci)):
            locus_index=support_loci[i]
            allele=support_alleles[i]
            snv=self.normal_sequence[0][locus_index]
            for j in range(self.strainsNum):
                hap_allele=snv[self.normal_sequence[1][j][locus_index]+2]
                if hap_allele == allele:
                    support_num[j] += 1
        #check which hap has most same alleles support_num.index(max(support_num))
        return self.most_support(support_num)

    def most_support(self,support_num):
        hap_order = np.argsort(np.array(support_num))[::-1]
        return hap_order

    def deletion_reads(self,deletion_index):
        link_reads=[]  #the reads number that shared with different haps, the copy number may be 0
        for i in range(self.strainsNum):
            link_reads.append(0)
        samfile = pysam.AlignmentFile(self.bamfile, "rb")
        for read in samfile.fetch(self.gene,float(self.deletion_region[deletion_index][0])-1,float(self.deletion_region[deletion_index][1])):
            #print (deletion_index, read.query_name, float(self.deletion_region[deletion_index][0])-1, float(self.deletion_region[deletion_index][1]))
            for i in range(self.strainsNum):
                if read.query_name in self.reads_support[i]:
                    link_reads[i] += 1
        print (deletion_index, link_reads, self.most_support(link_reads))
        return self.most_support(link_reads)

    def insertion_reads(self,deletion_index):
        link_reads=[]  #the reads number that shared with different haps, the copy number may be 0
        for i in range(self.strainsNum):
            link_reads.append(0)
        samfile = pysam.AlignmentFile(self.bamfile, "rb")
        for read in samfile.fetch('%s_%s'%(self.gene,self.deletion_region[deletion_index][0])):
            for i in range(self.strainsNum):
                if read.query_name in self.reads_support[i]:
                    link_reads[i] += 1
        return self.most_support(link_reads)

    def deletion_phase(self):
        for deletion_index in range(len(self.deletion_region)):
            # print (self.deletion_region[deletion_index])
            self.deletion_reads(deletion_index)

    def dup_assign(self):       
        #uniq reads for each dup type
        drb1_complex_seq, uniq_drb1_complex_reads = DRB1_complex_region(self.dup_file)
        #the relation between dup type and snv-haplotype
        share_num = []
        new_drb1_complex_seq = []
        for i in range(self.strainsNum):
            max_num = 0
            max_seq = ''
            for j in range(len(drb1_complex_seq)):
                num = 0
                for re in uniq_drb1_complex_reads[j]:
                    if re in self.reads_support[i]:
                        num+=1
                if num >= max_num:
                    max_num = num
                    max_seq = drb1_complex_seq[j]
                    print ('DRB1 assignment', i, j, max_num, len(drb1_complex_seq))
            new_drb1_complex_seq.append(max_seq)
        return new_drb1_complex_seq

    def split_seg(self):
        # print ('start split seg.')
        if self.gene == 'HLA_DRB1':
            my_drb1_complex_seq = self.dup_assign()
        normal_region, segs = self.generate_normal_region()
        id_name = {}
        gap = ''
        contain_dup_seg = ''
        for seg in segs:
            print ('seg', seg)
            if seg[2] == 'insertion':
                continue
            if self.gene == 'HLA_DRB1' and seg[0] < 3898 and seg[1] > 4400:
                contain_dup_seg = seg
                seg[2] = 'dup'
                seg_region = ' %s:%s-3898 %s:3898-4400 %s:4400-%s '%(self.gene,\
                seg[0],self.gene,self.gene,seg[1])
                seg_region_front = ' %s:%s-3898 '%(self.gene, seg[0])
                seg_region_dup = ' %s:3898-4400 '%(self.gene)
                seg_region_behind = ' %s:4400-%s '%(self.gene,seg[1])
                id_name[seg_region_front.strip()] = str(seg[0])+'>'
                id_name[seg_region_dup.strip()] = str(seg[0])+'='
                id_name[seg_region_behind.strip()] = str(seg[1])+'<'
            else:
                seg_region = ' %s:%s-%s '%(self.gene,seg[0],seg[1])
                id_name[seg_region.strip()] = str(seg[0]) + '_' + str(seg[1]) 
            gap += seg_region
        for i in range(self.strainsNum):
            order='%s/../bin/samtools faidx %s/../db/ref/hla.ref.extend.fa\
                %s |%s/../bin/bcftools\
                consensus -H %s %s/%s.rephase.vcf.gz  >%s/%s_%s_seg.fa'%(sys.path[0],sys.path[0],gap,sys.path[0],i+1,self.outdir,\
                self.gene,self.outdir,self.gene,i)
            os.system(order)
            fa_file = '%s/%s_%s_seg.fa'%(self.outdir,self.gene,i)
            seg_sequence = chrom_seq(fa_file)
            new_seg_sequence = {}
            for segseq in seg_sequence.keys():
                new_seg_sequence[id_name[segseq]] = seg_sequence[segseq]
            hap_seq = ''
            for seg in segs:
                # print (seg, str(seg[0]) + '_' + str(seg[1]))
               # print (str(seg[0]) + '_' + str(seg[1]) )
                if seg[2] == 'normal':
                    hap_seq += new_seg_sequence[str(seg[0]) + '_' + str(seg[1]) ]
                elif seg[2] == 'deletion':
                    deletion_index = seg[3]
                    assign_index = self.deletion_reads(deletion_index)[0]
                    print ('deletion assign_index', assign_index, self.deletion_region[deletion_index])
                    if  i == assign_index and self.deletion_region[deletion_index][2] == 1:
                        hap_seq += new_seg_sequence[str(seg[0]) + '_' + str(seg[1]) ]
                elif seg[2] == 'insertion':
                    # continue
                    deletion_index = seg[3]
                    assign_index = self.insertion_reads(deletion_index)[0]
                    print ('###########insertion', seg, assign_index, self.deletion_region[deletion_index][2])
                    insertion_seg = '%s_%s'%(self.gene, seg[0])
                    if self.deletion_region[deletion_index][2] == 2:                        
                        insert_seq = self.link_diploid_insertion(insertion_seg)
                        hap_seq += insert_seq[i]
                        # print ('#2 copy insertion', seg, assign_index,self.deletion_region[deletion_index][2])
                        # hap_seq += self.ins_seq[seg[0]]
                        
                    elif  i == assign_index and self.deletion_region[deletion_index][2] == 1:
                        # hap_seq += self.ins_seq[seg[0]]
                        # print ('#1 copy insertion', seg, assign_index,self.deletion_region[deletion_index][2])
                        hap_seq += self.consensus_insertion(insertion_seg)

                elif seg[2] == 'dup':
                    # print ('the seg contain dup region')
                    # the seg that contain the dup region
                    hap_seq += new_seg_sequence[str(seg[0])+'>']
                    #add the seq of chosen dup type
                    hap_seq += my_drb1_complex_seq[i]
                    # the seg that contain the dup region
                    hap_seq += new_seg_sequence[str(seg[1])+'<']                    
            hap_seq =  '>%s_%s\n'%(self.gene, i) + hap_seq[:]
            print ('________________', len(hap_seq))
            out = open('%s/hla.allele.%s.%s.fasta'%(self.outdir,i+1,self.gene), 'w')
            print (hap_seq, file = out)
            out.close()

    def link_diploid_insertion(self, insertion_seg):
        # insertion_seg = 'HLA_DRB1_6355'
        insert_reads_support = []
        for i in range(self.strainsNum):
            insert_reads_support.append([])

        in_vcf = VariantFile(self.vcf)
        sample = list(in_vcf.header.samples)[0]
        insert_phase_result = [[],[]]
        for record in in_vcf.fetch():
            geno = record.samples[sample]['GT']    
            depth = record.samples[sample]['AD']
            if record.chrom !=  insertion_seg:
                continue
            if geno == (1, 1):
                continue
            if geno == (0, 1):
                insert_phase_result[0].append([record.pos, record.ref])
                insert_phase_result[1].append([record.pos, record.alts[0]])
            elif geno == (1, 0):
                insert_phase_result[1].append([record.pos, record.ref])
                insert_phase_result[0].append([record.pos, record.alts[0]])  
            if len(insert_phase_result[0]) > 0:
                if len(insert_phase_result[1][-1][1]) != 1 or  len(insert_phase_result[0][-1][1]) != 1:
                    continue          

        samfile = pysam.AlignmentFile(self.bamfile, "rb")
        for read in samfile.fetch(insertion_seg):
            rivet_points=False
            support_alleles=[]
            support_loci=[]
            for i in range(len(insert_phase_result[0])):
                snv1 =insert_phase_result[0][i]
                snv2 =insert_phase_result[1][i]
                if int(snv1[0])-1 in read.get_reference_positions(full_length=True):
                    reads_index=read.get_reference_positions(full_length=True).index(int(snv1[0])-1)
                    if read.query_sequence[reads_index] == snv1[1]:
                        insert_reads_support[0].append(read.query_name)
                    elif read.query_sequence[reads_index] == snv2[1]:
                        insert_reads_support[1].append(read.query_name)
        r00 = 0
        for i in range(2):
            for j in range(len(insert_reads_support[i])):
                if insert_reads_support[i][j] in self.reads_support[i]:
                    r00 += 1
        r01 = 0
        for i in range(2):
            for j in range(len(insert_reads_support[i])):
                if insert_reads_support[i][j] in self.reads_support[1-i]:
                    r01 += 1
        fastq_seq = []
        for i in range(2):
            order = """
            %s/../bin/samtools faidx %s/newref_insertion.fa %s|%s/../bin/bcftools consensus -H %s %s  >%s/seq_%s_%s.fa
            """%(sys.path[0], self.outdir, insertion_seg, sys.path[0], i+1, self.vcf, self.outdir, i, insertion_seg)
            os.system(order)
            fastq_seq.append(read_fasta('%s/seq_%s_%s.fa'%(self.outdir, i, insertion_seg)))
        print ('link long indel supporting reads', r00, r01)
        if  r01 > r00:
            return [fastq_seq[1], fastq_seq[0]]
        else:
            return fastq_seq  

    def consensus_insertion(self, insertion_seg):
        order = """
        %s/../bin/samtools faidx %s/newref_insertion.fa %s|%s/../bin/bcftools consensus -H %s %s  >%s/seq
        """%(sys.path[0], self.outdir, insertion_seg, sys.path[0], 1, self.vcf, self.outdir)
        os.system(order)
        cons_seq = read_fasta('%s/seq'%(self.outdir))
        return cons_seq

def chrom_seq(file):
    f = open(file, 'r')
    seg_sequence = {}
    name = 'start'
    seq = ''
    for line in f:
        line = line.strip()
        if line[0] == '>':
            seg_sequence[name] = seq
            name = line[1:]
            seq = ''
        else:
            seq += line
    seg_sequence[name] = seq
    del seg_sequence['start']
    return seg_sequence

def read_fasta(file):
    seq=''
    for line in open(file, 'r'):
        if line[0] == '>':
            continue
        line=line.strip()
        seq+=line
    return seq
        
def segment_mapping_pre(fq1, fq2, ins_seq, outdir, gene, gene_ref):
    newref=outdir+'/newref_insertion.fa'
    os.system('cp %s %s'%(gene_ref, newref))
    for seg in ins_seq.keys():

        f = open(newref, 'a')
        print ('>%s_%s\n%s'%(gene, int(seg), ins_seq[seg]), file = f)
        f.close()
        # index the ref
    print ('New mapping starts to link long InDels.')
    map_call = """\
        bindir=%s/../bin/
        outdir=%s/ 
        sample='newref_insertion' 
        $bindir/samtools faidx %s 
        $bindir/bwa index %s
        group='@RG\\tID:sample\\tSM:sample'  #only -B 1
        $bindir/bwa mem -B 1 -O 1,1 -L 1,1 -U 1 -R $group -Y %s %s %s | $bindir/samtools view -q 1 -F 4 -Sb | $bindir/samtools sort > $outdir/$sample.sort.bam
        java -jar  $bindir/picard.jar MarkDuplicates INPUT=$outdir/$sample.sort.bam OUTPUT=$outdir/$sample.bam METRICS_FILE=$outdir/metrics.txt
        rm -rf $outdir/$sample.sort.bam 
        $bindir/samtools index $outdir/$sample.bam 
        $bindir/freebayes -f %s -p 2 $outdir/$sample.bam > $outdir/$sample.freebayes.1.vcf 
        cat $outdir/$sample.freebayes.1.vcf| sed -e 's/\//\|/g'>$outdir/$sample.freebayes.vcf 
        bgzip -f $outdir/$sample.freebayes.vcf 
        tabix -f $outdir/$sample.freebayes.vcf.gz
        """%(sys.path[0], outdir, newref, newref, newref, fq1, fq2, newref)
    os.system(map_call)
    # print (ins_seq)
    for ins in ins_seq.keys():
        ins_call = """%s/../bin/samtools faidx %s/newref_insertion.fa %s_%s |%s/../bin/bcftools consensus -H 1 %s/newref_insertion.freebayes.vcf.gz  >%s/fresh_ins.fa
        """%(sys.path[0],outdir,gene,int(ins),sys.path[0],outdir,outdir)
        # print ('#####################', ins, ins_call)
        os.system(ins_call)
        ins_seq[ins] = read_fasta('%s/fresh_ins.fa'%(outdir))
    # print (ins_seq)
    return ins_seq

    # map_call = """\
    #     bindir=%s/../bin/
    #     outdir=%s/ 
    #     sample='newref_insertion' 
    #     $bindir/samtools faidx %s 
    #     $bindir/bwa index %s
    #     group='@RG\\tID:sample\\tSM:sample'  #only -B 1
    #     /home/wangmengyao/packages/Novoalign/novocraft/novoindex %s.ndx %s
    #     /home/wangmengyao/packages/Novoalign/novocraft/novoalign -g 10 -x 1 -F STDFQ -o SAM -o FullNW  -d %s.ndx -f %s %s| $bindir/samtools view -q 1 -F 4 -Sb | $bindir/samtools sort > $outdir/$sample.sort.bam
    #     java -jar  $bindir/picard.jar MarkDuplicates INPUT=$outdir/$sample.sort.bam OUTPUT=$outdir/$sample.bam METRICS_FILE=$outdir/metrics.txt
    #     rm -rf $outdir/$sample.sort.bam 
    #     $bindir/samtools index $outdir/$sample.bam 
    #     $bindir/freebayes -f %s -p 2 $outdir/$sample.bam > $outdir/$sample.freebayes.vcf 
    #     """%(sys.path[0], outdir, newref, newref, newref, newref, newref, fq1, fq2, newref)
        # -B 1 -O 1,1 -L 1,1 -U 1 
    # print (map_call)
    
def segment_mapping(fq1, fq2, ins_seq, outdir, gene, gene_ref):
    newref=outdir+'/newref_insertion.fa'
    os.system('cp %s %s'%(gene_ref, newref))
    for seg in ins_seq.keys():

        f = open(newref, 'a')
        print ('>%s_%s\n%s'%(gene, int(seg), ins_seq[seg]), file = f)
        f.close()
        # index the ref
    print ('New mapping starts to link long InDels.')
    map_call = """\
        bindir=%s/../bin/
        outdir=%s/ 
        sample='newref_insertion' 
        $bindir/samtools faidx %s 
        $bindir/bwa index %s
        group='@RG\\tID:sample\\tSM:sample'  #only -B 1
        $bindir/bwa mem -B 1 -O 1,1 -L 1,1 -U 1 -R $group -Y %s %s %s | $bindir/samtools view -q 1 -F 4 -Sb | $bindir/samtools sort > $outdir/$sample.sort.bam
        java -jar  $bindir/picard.jar MarkDuplicates INPUT=$outdir/$sample.sort.bam OUTPUT=$outdir/$sample.bam METRICS_FILE=$outdir/metrics.txt
        rm -rf $outdir/$sample.sort.bam 
        $bindir/samtools index $outdir/$sample.bam 
        $bindir/freebayes -f %s -p 2 $outdir/$sample.bam > $outdir/$sample.freebayes.vcf 
        """%(sys.path[0], outdir, newref, newref, newref, fq1, fq2, newref)
    os.system(map_call)

def get_copy_number(outdir, deletion_region, gene, ins_seq):
    os.system('%s/../bin/samtools depth -a %s/newref_insertion.bam >%s/newref_insertion.depth'%(sys.path[0],outdir, outdir))
    normal_depth = []
    deletions_depth_list = []
    for i in range(len(deletion_region)):
        deletions_depth_list.append([])

    for line in open('%s/newref_insertion.depth'%(outdir)):
        array = line.strip().split()
        if array[0] != gene:
            continue
        deletion_flag = False
        for i in range(len(deletion_region)):
            if float(array[1]) >= float(deletion_region[i][0]) and float(array[1]) < float(deletion_region[i][1]):
                deletions_depth_list[i].append(float(array[2]))
                deletion_flag = True
        if deletion_flag == False:
            normal_depth.append(float(array[2]))

    insertions_depth_list = {}
    for seg in ins_seq.keys():
        chrom_name = '%s_%s'%(gene, int(seg))
        insertions_depth_list[chrom_name] = []
    # print (insertions_depth_list.keys())
    
    for line in open('%s/newref_insertion.depth'%(outdir)):
        array = line.strip().split()
        if array[0] in insertions_depth_list.keys():
            insertions_depth_list[array[0]].append(float(array[2]))


    for i in range(len(deletion_region)):
        # deletion_region[i] += [np.mean(deletions_depth_list[i])/np.mean(normal_depth), zero_per(deletions_depth_list[i])]
        if float(deletion_region[i][0]) == float(deletion_region[i][1]):
            chrom_name = '%s_%s'%(gene, int(deletion_region[i][0]))
            # print ('compute assign index', np.mean(insertions_depth_list[chrom_name]),np.mean(normal_depth))
            if np.mean(insertions_depth_list[chrom_name])/np.mean(normal_depth) > 0.5:
                deletion_region[i] += [2]
            else:
                deletion_region[i] += [1]
        else:
            print ('compute copy number for deletion', deletion_region[i], zero_per(deletions_depth_list[i]))
            if zero_per(deletions_depth_list[i]) > 0.2:
                deletion_region[i] += [0]
            else:
                deletion_region[i] += [1]
        print ('### copy number', deletion_region[i])
    
    return deletion_region

def zero_per(list):
    zero_num = 0
    for li in list:
        if li < 3:
            zero_num  += 1
    return zero_num/len(list)

def uniq_reads(raw_reads_set):
    dup_type_Num = len(raw_reads_set)
    uniq_reads_set = []
    for i in range(dup_type_Num):
        uniq_set = []
        for ele in raw_reads_set[i]:
            uniq_flag = True
            for j in range(dup_type_Num):
                if i == j:
                    continue
                if ele in raw_reads_set[j]:
                    uniq_flag = False
            if uniq_flag == True:
                uniq_set.append(ele)
        uniq_reads_set.append(uniq_set)
    # print ('uniq reads', len(uniq_reads_set[0]), len(uniq_reads_set[1]))
    return uniq_reads_set

def DRB1_complex_region(drb1_complex_file):
    drb1_complex_seq = []
    drb1_complex_reads = []
    for line in open(drb1_complex_file, 'r'):
        line = line.strip()
        array = line.split()
        drb1_complex_seq.append(array[5])
        reads_list = []
        raw_reads_list = array[6].split(';')
        for reads in raw_reads_list[:-1]:
            reads_list.append(reads[:-3])
        drb1_complex_reads.append(reads_list)
    # print ('There are %s dup types.'%(len(drb1_complex_seq)))
    uniq_drb1_complex_reads = uniq_reads(drb1_complex_reads)
    return drb1_complex_seq, uniq_drb1_complex_reads

def sv2fasta(ref, seg_order, index_locus, ins_seq, outdir):
    ref_seq = read_fasta(ref)
    normal_dict = {}
    for seg in index_locus.keys():
        if seg in ins_seq.keys():
            continue
        normal_dict[seg] = ref_seq[index_locus[seg][0]-1 : index_locus[seg][1]-1]
    for i in range(len(seg_order)):
        seg_array = seg_order[i].strip().split()
        hap_seq = '>sv_hap_%s\n'%(i)
        out = open(outdir + '/sv_hap_%s.fa'%(i), 'w')
        for arr in seg_array:
            seg_name = arr[:-1]
            if seg_name in ins_seq.keys():
                my_seq = ins_seq[seg_name]
            else:
                my_seq = normal_dict[seg_name]
            hap_seq += my_seq
        print (hap_seq, file = out)
        out.close()

def dup_region_type(outdir, strainsNum, bamfile):
    order = r"""
        bam=%s
        outdir=%s
        k=%s
        pos=HLA_DRB1:3898-4400        
        ref=%s/../db/ref/DRB1_dup_extract_ref.fasta
        %s/../bin/samtools view -f 64 $bam $pos| cut -f 1,6,10|sort|uniq |awk '{OFS="\n"}{print ">"$1"##1 "$2,$3}' > $outdir/extract.fa
        %s/../bin/samtools view -f 128 $bam $pos| cut -f 1,6,10|sort|uniq |awk '{OFS="\n"}{print ">"$1"##2 "$2,$3}' >> $outdir/extract.fa
        %s/../bin/blastn -query $outdir/extract.fa -out $outdir/extract.read.blast -db $ref -outfmt 6 -strand plus  -penalty -1 -reward 1 -gapopen 4 -gapextend 1
        perl %s/count.read.pl $outdir
        less $outdir/DRB1.hla.count| sort -k3,3nr -k4,4nr | head -n $k |awk '$3>0.7'|awk '$4>5' >$outdir/select.DRB1.seq.txt
        """%(bamfile, outdir, strainsNum, sys.path[0], sys.path[0], sys.path[0],sys.path[0], sys.path[0])
    os.system(order)

def long_InDel_breakpoints(bfile):
    sv_dict = {}
    if not os.path.isfile(bfile):
        return sv_dict
    f = open(bfile, 'r')
    for line in f:
        line = line.strip()
        array = line.split()
        if array[0] != array[3]:
            continue
        if array[0] == 'HLA_DRB1':
            if int(array[1]) > 3800 and int(array[1]) < 4500:
                continue
            if int(array[4]) > 3800 and int(array[4]) < 4500:
                continue
        sv = [array[1], array[4], array[6]]
        #sv = [array[1], array[4], array[6], int(array[7])]
        if array[0] not in sv_dict:
            sv_dict[array[0]] = [sv]
        else:
            sv_dict[array[0]].append(sv)
    return sv_dict

def get_deletion_region(long_indel_file, gene):
    sv_dict = long_InDel_breakpoints(long_indel_file) # record the long indel
    if gene in sv_dict.keys():
        sv_list = sv_dict[gene]
    else:
        sv_list = []
    # print (sv_list)
    deletion_region = []
    ins_seq = {}
    insertion = []
    points = []
    new_deletion_region = []
    for sv in sv_list:
        if sv[0] != sv[1]:
            points.append(int(float(sv[0])))
            points.append(int(float(sv[1])))
            deletion_region.append([int(float(sv[0])), int(float(sv[1]))])
            # deletion_region.append([int(float(sv[0])), int(float(sv[1])), int(sv[3])])
        else:
            #remove redundant insertions
            uniq_ins = True
            for region in new_deletion_region:
                if region[0] != region[1]:
                    continue
                if abs(int(sv[0]) - region[0]) < 50:
                    uniq_ins = False
            if uniq_ins:
                # new_deletion_region.append([int(float(sv[0])), int(float(sv[1])), int(sv[3])])
                new_deletion_region.append([int(float(sv[0])), int(float(sv[1]))])
                seg = float(sv[0])
                ins_seq[seg] = sv[2]                

    start = 1
    split_segs = []
    for p in sorted(points):
        if start == p:
            continue
        split_segs.append([start, p])
        start = p
  
    for segs in split_segs:
        delete_flag = False
        for re in deletion_region:
            if segs[0] >= re[0] and segs[1] <= re[1]:
                delete_flag = True
        if delete_flag and segs[1] - segs[0] > 4:
            new_deletion_region.append(segs)
    deletion_region = new_deletion_region
    # print ('new_deletion_region',deletion_region)
    while True:
        flag = True
        new_deletion_region = deletion_region[:]
        for i in range(len(deletion_region) - 1):
            if deletion_region[i+1][0] < deletion_region[i][0]:
                flag = False
                new_deletion_region[i] = deletion_region[i+1]
                new_deletion_region[i+1] = deletion_region[i]
                # print ('ite', i, new_deletion_region)
                break
            elif deletion_region[i][1] > deletion_region[i+1][1]:
                new_deletion_region[i] = [deletion_region[i][0], deletion_region[i+1][0]]
                new_deletion_region[i+1] = [deletion_region[i+1][0], deletion_region[i+1][1]]
                new_deletion_region.append([deletion_region[i+1][1], deletion_region[i][1]])
                break
        deletion_region = new_deletion_region[:]
        # print (deletion_region)
        if flag:
            break
    print ('#ordered deletion region:', deletion_region)
    return deletion_region, ins_seq

def split_vcf(gene, outdir, deletion_region):
    vcf = '%s/%s.vcf.gz'%(outdir,gene)
    os.system('tabix -f %s'%(vcf))
    # if len(deletion_region) == 0:
    #     print ('no sv!')
    #     return 0
    vcf_gap = []
    start = 1001
    break_points_list = [3950]
    # for dele in deletion_region:
    #     if abs(start - dele[0]) < 1:
    #         continue
    #     break_points_list.append(dele[0])
    break_points_list = sorted(break_points_list)
    start = 1001
    for b_point in break_points_list: 
        if b_point - start < 500:
            continue
        if b_point >6000 and b_point < 7000:
            continue
        vcf_gap.append([start, b_point])
        start = b_point
    if focus_region()[gene][1] - start >= 500:
        vcf_gap.append([start, focus_region()[gene][1]])
    else:
        vcf_gap[-1][1] = focus_region()[gene][1] 
    os.system('rm %s/%s_part_*_*_*.vcf'%(outdir, gene))
    i = 0
    for gap in vcf_gap:
        order = "%s/../bin/bcftools filter -t %s:%s-%s %s -o %s/%s_part_%s_%s_%s.vcf"%(sys.path[0],gene, gap[0], gap[1], vcf, outdir, gene, i, gap[0], gap[1])
        os.system(order)
        i+=1
    print (vcf_gap)
    return break_points_list

def get_unphased_loci(outdir, gene, invcf, snp_list, spec_vcf):
    """
    Input: the phased vcf of SpecHap
    Return: the unphased loci, and refined vcf file
    """
    
    bp = open(outdir + '/%s_break_points_spechap.txt'%(gene), 'w')
    print ('#gene   locus   00      01      10      11      points_num      next_locus', file = bp)
    m = VariantFile(invcf)
    out = VariantFile(spec_vcf,'w',header=m.header)
    sample = list(m.header.samples)[0]
    add_block = 1
    i = 0
    used_locus = []
    for record in m.fetch():
        # if record.qual < 1
        if record.chrom != gene:
            continue
        if record.samples[sample].phased != True:
            #record.samples[sample]['GT']= (1,1)
            record.samples[sample]['PS'] = add_block
            if record.samples[sample]['GT'] != (1,1) and record.samples[sample]['GT'] != (0,0) and record.samples[sample]['GT'] != (2,2):
                if i > 0 and past_record.pos not in used_locus:
                    used_locus.append(past_record.pos)
                    print (past_record.chrom, past_record.pos, '- - - -', 20, past_record.pos + 100, file = bp)
            record.samples[sample].phased = True
        if record.samples[sample]['PS'] != add_block:
            if i > 0 and past_record.pos not in used_locus:
                used_locus.append(past_record.pos)
                print (past_record.chrom, past_record.pos, '- - - -', 20, past_record.pos + 100, file = bp)
            add_block = record.samples[sample]['PS']
        if record.samples[sample]['GT'] != (1,1) and record.samples[sample]['GT'] != (0,0)  and record.samples[sample]['GT'] != (2,2):
            i += 1
            past_record = record
        # print (record.pos, break_points)
        out.write(record)
    m.close()
    out.close()
    bp.close()

def phase_insertion(gene, outdir, hla_ref, shdir):
    order = """
    sample=%s
    outdir=%s
    ref=%s
    cat $outdir/newref_insertion.freebayes.vcf|grep '#'>$outdir/filter_newref_insertion.freebayes.vcf
    awk -F'\t' '{if($6>5) print $0}' $outdir/newref_insertion.freebayes.vcf|grep -v '#' >>$outdir/filter_newref_insertion.freebayes.vcf
    %s/../bin/ExtractHAIRs --triallelic 1 --mbq 4 --mmq 0 --indels 1 \
    --ref $ref --bam $outdir/newref_insertion.bam --VCF $outdir/filter_newref_insertion.freebayes.vcf --out $outdir/$sample.fragment.file > spec.log 2>&1
    sort -n -k3 $outdir/$sample.fragment.file >$outdir/$sample.fragment.sorted.file
    bgzip -f $outdir/filter_newref_insertion.freebayes.vcf
    tabix -f $outdir/filter_newref_insertion.freebayes.vcf.gz
    %s/../bin/SpecHap --window_size 15000 -N --vcf $outdir/filter_newref_insertion.freebayes.vcf.gz --frag $outdir/$sample.fragment.sorted.file --out $outdir/$sample.insertion.phased.raw.vcf
    cat $outdir/$sample.insertion.phased.raw.vcf| sed -e 's/1\/1/1\|1/g'>$outdir/$sample.insertion.phased.vcf
    bgzip -f $outdir/$sample.insertion.phased.vcf
    tabix -f $outdir/$sample.insertion.phased.vcf.gz
    """%(gene, outdir, hla_ref, sys.path[0], shdir)
    os.system(order)
    print ('insertion phasing done.')

def compute_allele_frequency(geno_set,beta_set):
    # compute allele frequency with least square
    locus_num = 0
    alpha = np.array([0.0, 0.0])
    for i in range(len(beta_set)):
        beta = beta_set[i][1]
        if geno_set[i][0] == 0:
            alpha[0] += (1-beta)
            alpha[1] += beta
            locus_num += 1
        elif geno_set[i][0] == 1:
            alpha[0] += beta
            alpha[1] += (1-beta)
            locus_num += 1
    if locus_num > 0:
        freqs = alpha/locus_num
        return [round(freqs[0], 3), round(freqs[1], 3)]
    else:
        return [1, 0]

def allele_imba(freqs):
    """
    Utilizing allelic imbalance information to phase
    get the linkage info from allele frequencies at each variant locus
    return the linkage info with a SpecHap acceptable format
    """
    
    f = open(outdir + '/fragment.imbalance.file', 'w')
    base_q = 60 * args.weight_imb
    if base_q >= 1:
        locus_num = len(freqs)
        mat = np.zeros((2*locus_num, 2*locus_num))
        for i in range(locus_num):
            z = 0
            for j in range(i+1, locus_num):
                if z == 1:
                    break
                same = max([ freqs[i][0] *  freqs[j][0], freqs[i][1] *  freqs[j][1] ])
                reverse = max([ freqs[i][0] *  freqs[j][1], freqs[i][1] *  freqs[j][0] ])
                linkage_name = "linkage:%s:%s"%(i, j)
                print('2 %s:1 %s %s %s %s ?? %s'%(linkage_name, i+1, 0, j+1, 0, int(base_q*same)), file=f)
                print('2 %s:2 %s %s %s %s ?? %s'%(linkage_name, i+1, 0, j+1, 1, int(base_q*reverse)), file=f)
                z += 1
    f.close()

def run_SpecHap():
         
    # get linkage info from NGS data
    if new_formate:
        order = '%s/../bin/ExtractHAIRs --new_format 1 --triallelic 1 --indels 1 --ref %s --bam %s --VCF %s\
            --out %s/fragment.file'%(sys.path[0], hla_ref, bamfile, gene_vcf, outdir)
    else:
        order = '%s/../bin/ExtractHAIRs --triallelic 1 --indels 1 --ref %s --bam %s --VCF %s \
        --out %s/fragment.file'%(sys.path[0], hla_ref, bamfile, gene_vcf, outdir)
    os.system(order)
    extract_linkage_for_indel(bamfile,snp_list,snp_index_dict,outdir) # linkage for indel
    allele_imba(beta_set) # linkage from allele imbalance
    os.system('cat %s/fragment.file %s/fragment.add.file %s/fragment.imbalance.file>%s/fragment.all.file'%(outdir,\
        outdir, outdir, outdir))
    
    # the order to phase with only ngs data.
    order='%s/../bin/SpecHap --window_size 15000 --vcf %s --frag %s/fragment.sorted.file --out \
    %s/%s.specHap.phased.vcf'%(sys.path[0],gene_vcf, outdir, outdir,gene)


    # integrate phase info from pacbio data if provided.
    if args.tgs != 'NA':
        tgs = """
        fq=%s
        ref=%s
        outdir=%s
        bin=%s/../bin
        sample=my
        $bin/minimap2 -a $ref $fq > $outdir/$sample.tgs.sam
        $bin/samtools view -F 2308 -b -T $ref $outdir/$sample.tgs.sam > $outdir/$sample.tgs.bam
        $bin/samtools sort $outdir/$sample.tgs.bam -o $outdir/$sample.tgs.sort.bam
        $bin/ExtractHAIRs --triallelic 1 --pacbio 1 --indels 1 --ref $ref --bam $outdir/$sample.tgs.sort.bam --VCF %s --out $outdir/fragment.tgs.file
        """%(args.tgs, hla_ref, outdir, sys.path[0], gene_vcf)
        print ('extract linkage info from pacbio TGS data.')
        os.system(tgs)
        os.system('cat %s/fragment.tgs.file >> %s/fragment.all.file'%(outdir, outdir))
        order = '%s/../bin/SpecHap -P --window_size 15000 --vcf %s --frag %s/fragment.sorted.file \
        --out %s/%s.specHap.phased.vcf'%(sys.path[0],gene_vcf, outdir, outdir,gene)
        # print (order)

    # nanopore
    if args.nanopore != 'NA':
        tgs = """
        fq=%s
        ref=%s
        outdir=%s
        bin=%s/../bin
        sample=my
        $bin/minimap2 -a $ref $fq > $outdir/$sample.tgs.sam
        $bin/samtools view -F 2308 -b -T $ref $outdir/$sample.tgs.sam > $outdir/$sample.tgs.bam
        $bin/samtools sort $outdir/$sample.tgs.bam -o $outdir/$sample.tgs.sort.bam
        $bin/ExtractHAIRs --triallelic 1 --ONT 1 --indels 1 --ref $ref --bam $outdir/$sample.tgs.sort.bam --VCF %s --out $outdir/fragment.nanopore.file
        # python %s/whole/edit_linkage_value.py $outdir/fragment.raw.nanopore.file 0 $outdir/fragment.nanopore.file
        # rm $outdir/fragment.nanopore.file
        # touch $outdir/fragment.nanopore.file

        """%(args.nanopore, hla_ref, outdir, sys.path[0], gene_vcf, sys.path[0])
        print ('extract linkage info from nanopore TGS data.')
        os.system(tgs)
        os.system('cat %s/fragment.nanopore.file >> %s/fragment.all.file'%(outdir, outdir))
        order = '%s/../bin/SpecHap -N --window_size 15000 --vcf %s --frag %s/fragment.sorted.file \
        --out %s/%s.specHap.phased.vcf'%(sys.path[0],gene_vcf, outdir, outdir,gene)

    # hic 
    if args.hic_fwd != 'NA' and args.hic_rev != 'NA':
        tgs = """
        fwd_hic=%s
        rev_hic=%s
        ref=%s
        outdir=%s
        bin=%s/../bin
        sample=my
        group='@RG\tID:'$sample'\tSM:'$sample
        $bin/bwa mem -5SP -Y -U 10000 -L 10000,10000 -O 7,7 -E 2,2 $ref $fwd_hic $rev_hic >$outdir/$sample.tgs.raw.sam
        cat $outdir/$sample.tgs.raw.sam|grep -v 'XA:'|grep -v 'SA:'>$outdir/$sample.tgs.sam
        $bin/samtools view -F 2308 -b -T $ref $outdir/$sample.tgs.sam > $outdir/$sample.tgs.bam
        $bin/samtools sort $outdir/$sample.tgs.bam -o $outdir/$sample.tgs.sort.bam
        $bin/ExtractHAIRs --new_format 1 --triallelic 1 --hic 1 --indels 1 --ref $ref --bam $outdir/$sample.tgs.sort.bam --VCF %s --out $outdir/fragment.hic.file
        # python %s/whole/edit_linkage_value.py $outdir/fragment.raw.hic.file 10 $outdir/fragment.hic.file
        # rm $outdir/fragment.hic.file
        # touch $outdir/fragment.hic.file
        """%(args.hic_fwd, args.hic_rev, hla_ref, outdir, sys.path[0], gene_vcf, sys.path[0])
        print ('extract linkage info from HiC data.')
        os.system(tgs)
        os.system('cat %s/fragment.hic.file >> %s/fragment.all.file'%(outdir, outdir))
        # gene_vcf = '%s/%s.new.vcf.gz'%(outdir, gene)
        order = '%s/../bin/SpecHap -H --new_format --window_size 15000 --vcf %s --frag %s/fragment.sorted.file \
        --out %s/%s.specHap.phased.vcf'%(sys.path[0],gene_vcf, outdir, outdir,gene)
        print (order)

    # 10x genomics
    if args.tenx != 'NA':
        tgs = """
            fq=%s
            ref=%s
            outdir=%s
            bin=%s/../bin
            sample=%s
            gene=%s
            echo $gene
            
            if [ $gene == "HLA_A" ];
                then
                    $bin/longranger wgs --id=1 --fastqs=$fq --reference=%s/../db/ref/refdata-hla.ref.extend --sample=$sample --sex m --localcores=8 --localmem=32 --jobmode=local --vconly
            fi
            if [ $gene == "HLA_DRB1" ];
            then
            rm -r ./1
            fi
            bam=./1/outs/phased_possorted_bam.bam

            $bin/extractHAIRS  --new_format 1 --triallelic 1 --10X 1 --indels 1 --ref $ref --bam $bam --VCF %s --out $outdir/fragment.tenx.file
            $bin/BarcodeExtract $bam $outdir/barcode_spanning.bed
            bgzip -f -c $outdir/barcode_spanning.bed > $outdir/barcode_spanning.bed.gz
            tabix -f -p bed $outdir/barcode_spanning.bed.gz
        
        """%(args.tenx, hla_ref, outdir, sys.path[0], args.sample_id, gene, sys.path[0], gene_vcf)
        print ('extract linkage info from 10 X data.')
        # print (tgs)
        os.system(tgs)

        os.system('cat %s/fragment.tenx.file > %s/fragment.all.file'%(outdir, outdir))
        order = '%s/../bin/SpecHap -T --frag_stat %s/barcode_spanning.bed.gz --new_format --window_size 15000 \
        --vcf %s --frag %s/fragment.sorted.file\
        --out %s/%s.specHap.phased.vcf'%(sys.path[0],outdir,gene_vcf, outdir, outdir,gene)
        # print (order)
    
    if new_formate:
        os.system('sort -n -k6 %s/fragment.all.file >%s/fragment.sorted.file'%(outdir, outdir))
    else:
        os.system('sort -n -k3 %s/fragment.all.file >%s/fragment.sorted.file'%(outdir, outdir))


    # phase small variants with spechap and find the unphased points
    # os.system('tabix -f %s'%(gene_vcf))
    os.system(order)
    get_unphased_loci(outdir, gene, raw_spec_vcf, snp_list, spec_vcf)
    os.system('tabix -f %s'%(spec_vcf))

def link_blocks():
    """
    Phasing unlinked blocks guided by HLA database
    """
    # link phase blocks with database
    # if gene == 'HLA_DRB1':
    #     split_vcf(gene, outdir, deletion_region)  
    print ('Start link blocks with database...')
    # if gene == 'HLA_DRB1':
    #     reph='perl %s/whole/rephase.DRB1.pl %s/%s_break_points_spechap.txt\
    #         %s %s %s/%s_break_points_phased.txt %s %s'%(sys.path[0], outdir,gene,outdir,strainsNum,outdir,\
    #         gene,args.block_len,args.points_num)
    # else:
    #     reph='perl %s/whole/rephaseV1.pl %s/%s_break_points_spechap.txt\
    #         %s %s %s/%s_break_points_phased.txt %s %s'%(sys.path[0],outdir,gene,outdir,strainsNum,outdir,\
    #         gene,args.block_len,args.points_num)
    # map the haps in each block to thee database
    reph='perl %s/whole/read_unphased_block.pl %s/%s_break_points_spechap.txt\
        %s 2 %s/%s_break_points_score.txt'%(sys.path[0],outdir,gene,outdir,outdir,gene)
    os.system(str(reph))
    # phase block with spectral graph theory
    spec_block = "python3 %s/phase_unlinked_block.py %s/%s_break_points_score.txt %s/%s_break_points_phased.txt"\
        %(sys.path[0],outdir,gene,outdir,gene)
    os.system(str(spec_block))

    seq_list = read_spechap_seq(spec_vcf, snp_list) # the haplotype obtained from SpecHap  
    update_seqlist = block_phase(outdir,seq_list,snp_list,gene,gene_vcf,rephase_vcf)  # refine the haplotype
    return update_seqlist

def get_insertion_linkage(ins_seq):
    """
    To get the linkage information for long insertions
    The long insertion sequence and the reference are combined to generate a modified reference
    Map the reads to the modified reference
    """
    if len(ins_seq) > 0:
        ins_seq = segment_mapping_pre(fq1, fq2, ins_seq, outdir, gene, hla_ref)
        segment_mapping(fq1, fq2, ins_seq, outdir, gene, hla_ref)
    else:
        os.system('cp %s/%s.bam %s/newref_insertion.bam'%(outdir, gene.split('_')[-1], outdir))
        os.system('%s/../bin/samtools index %s/newref_insertion.bam'%(sys.path[0], outdir))
        os.system('zcat %s > %s/newref_insertion.freebayes.vcf'%(gene_vcf, outdir))
    return ins_seq


if __name__ == "__main__":   
    if len(sys.argv)==1:
        print (Usage%{'prog':sys.argv[0]})
    else:     
        bamfile,outdir,snp_dp,indel_len,freq_bias=args.bamfile,args.outdir,args.snp_dp,args.indel_len,args.freq_bias           
        snp_qual,gene,fq1,fq2,vcffile,long_indel_file = args.snp_qual,args.gene,args.fq1,args.fq2,args.vcf,args.sv
        strainsNum = 2 # two hap for each sample
        hla_ref = '%s/../db/ref/hla.ref.extend.fa'%(sys.path[0])
        gene_vcf = "%s/%s.vcf.gz"%(outdir, gene) # gene-specific variants 
        raw_spec_vcf = '%s/%s.specHap.phased.vcf'%(outdir,gene)
        spec_vcf = outdir + '/%s.spechap.vcf.gz'%(gene)
        rephase_vcf = '%s/%s.rephase.vcf.gz'%(outdir,gene)
        if not os.path.exists(outdir):
            os.system('mkdir '+ outdir) 
        new_formate = False  # different para for ExtractHAIRs
        # if we have 10x or hic data, use new formate for linkage info
        # required by SpecHap
        if args.hic_fwd != 'NA' or args.tenx != 'NA':
            new_formate = True    

        # read long Indels
        deletion_region, ins_seq = get_deletion_region(long_indel_file, gene)       
        # read small variants
        snp_list,beta_set,snp_index_dict = read_vcf(vcffile,outdir,snp_dp,bamfile,indel_len,gene,\
            freq_bias,strainsNum,deletion_region,snp_qual,gene_vcf)   
        
        if len(snp_list)==0:
            print ('No heterozygous locus, no need to phase.')
            gene_profile = no_snv_gene_phased(gene_vcf, outdir, gene, strainsNum)
        else:  
            # phase small variants          
            run_SpecHap()
            # phase unlinked blocks
            update_seqlist = link_blocks()          
            # compute haplotype frequency with least-square
            fresh_alpha = compute_allele_frequency(update_seqlist, beta_set) 
            # output haplotype frequencies
            freq_output(outdir, gene, fresh_alpha)
            # get the phase info to phase long Indel later
            gene_profile = gene_phased(update_seqlist,snp_list,gene)
            print ('Samll variant-phasing of %s is done! Haplotype ratio is %s:%s'%(gene, fresh_alpha[0], fresh_alpha[1]))

        # realign reads to the modified reference generated by combining long 
        # insertion sequence and the original reference
        ins_seq = get_insertion_linkage(ins_seq)
        # get copy number of long Indels
        deletion_region = get_copy_number(outdir, deletion_region, gene, ins_seq) 

        if gene == 'HLA_DRB1':
            # DRB1 contains long duplicates in the region 3900-4400 bp
            # Infer the sequence in this region
            dup_region_type(outdir, strainsNum, bamfile)
            dup_file = outdir +'/select.DRB1.seq.txt'

        if len(ins_seq) > 0:
            # after map reads to the long insertion sequence
            # there can be hete variants
            # get consensus sequence if copy number is 1 
            # phase the variants to get two haps if copy number is 2
            phase_insertion(gene, outdir, args.ref, sys.path[0])

        # phase long indels
        sh = Share_reads(deletion_region, outdir, strainsNum, gene, gene_profile, ins_seq)
        sh.split_seg()


