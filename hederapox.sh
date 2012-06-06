#!/bin/sh

export PYTHONPATH=${PYTHONPATH}:/home/ubuntu/proj3/ripl:/home/ubuntu/proj3/riplpox
bw=$2
pox/pox.py --no-cli riplpox.hederapox --topo=ft,$1 --routing=hashed --bw=$bw
