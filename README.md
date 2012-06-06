Hedera Mininet Experiment
=====

USAGE
---

Run test.sh 5 60 for full automated reproduction of our results. 
This runs each experiment 5 times and will take around 26 hours.

For a smaller test suite, try using test.sh 1 30, which should
complete in 3 hours.

REPLICATION INSTRUCTIONS
---
1. Launch a new instance in the US West (Oregon) region on EC2, with cs244-mininet-mptcp-dctcp. A c1.medium instance should be sufficient for replicating our results.

2. When the instance is up, sudo edit the default configuration in `/boot/grub/menu.lst`. Change line 14 from 2 to 0.

3. `sudo reboot`

4. After the instance is up, run 
``sudo apt-get install -y linux-headers-`uname -r```

`sudo dkms install openvswitch/1.4.0`

`sudo service openvswitch-switch restart`

5. Check out the code repository
`git clone https://github.com/strategist333/hedera.git`

`cd hedera`

6. Run the test script. Our full results can be replicated using test.sh 5 60, but for brevity we recommend test.sh 1 30. Even so, we recommend using screen to prevent accidental network drops from terminating the experiment early.
`screen`

`sudo ./test.sh 5 60`