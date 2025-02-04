"""
The raw reads generated by LRSIM has /1 or /2 in read name.
The /1 or /2 will cause bug in Longranger
this script remove the /1 and /2 in read name

wangshuai, wshuai294@gmail.com
"""


import re
import sys
import os


def refine(file):
    f = open(inpath + "/" + file, 'r')
    out = open(outpath + "/" + file, 'w')
    for line in f:
        line = line.strip()
        line = re.sub(r'/1', "", line)
        line = re.sub(r'/2', "", line)
        print (line, file = out)
    out.close()
    f.close()

def main():
    for file in os.listdir(inpath):
        refine(file)


if __name__ == "__main__":
    # file="fq/child_1_S1_L001_R1_001.fastq"
    inpath=sys.argv[1] # path contains raw reads generated by LRSIM
    outpath=sys.argv[2] # path contains refined reads
    # refine(file)
    main()