#!/bin/bash

dir=$1
k=$2
maxy=$3
km1=$((k - 1))
kdiv2=$((km1 / 2))
python util/plot_rate.py \
       -f $dir/hedera/bwm.txt $dir/ecmp/bwm.txt $dir/control/bwm.txt $dir/random/bwm.txt $dir/st/bwm.txt \
       --legend Hedera ECMP Nonblocking Random ST \
       --maxy $maxy \
       --xlabel 'Time (s)' \
       --ylabel 'Rate (Mbps)' \
       --total \
       -i "(([0-$km1]_[0-$kdiv2]_1-eth\d*[24680])|(s1-eth.*))" \
       -o $dir/summary.png
