#!/usr/bin/env python3
# Copyright (c) 2015-2017 The Bitcoin Unlimited developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

import time
import random
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal
from test_framework.util import *
from test_framework.blocktools import *
import test_framework.script as script
import pdb
import sys
if sys.version_info[0] < 3: raise "Use Python 3"
import logging
logging.basicConfig(format='%(asctime)s.%(levelname)s: %(message)s', level=logging.INFO)

class BUIP055Test (BitcoinTestFramework):
    def __init__(self,extended=False):
      self.extended = extended
      BitcoinTestFramework.__init__(self)

    def setup_network(self, split=False):
        self.nodes = []
        self.nodes.append(start_node(0,self.options.tmpdir, ["-rpcservertimeout=0"], timewait=60*10))
        self.nodes.append(start_node(1,self.options.tmpdir, ["-rpcservertimeout=0"], timewait=60*10))
        self.nodes.append(start_node(2,self.options.tmpdir, ["-rpcservertimeout=0"], timewait=60*10))
        self.nodes.append(start_node(3,self.options.tmpdir, ["-rpcservertimeout=0"], timewait=60*10))
        interconnect_nodes(self.nodes)
        self.is_network_split=False
        self.sync_all()

    def testDefaults(self):
        for n in self.nodes:
            t = n.get("mining.fork*")
            assert(t['mining.forkBlockSize'] == 2000000) # REQ-4-2
            assert(t['mining.forkExcessiveBlock'] == 8000000) # REQ-4-1
            assert(t['mining.forkTime'] == 1501590000) # REQ-2

    def testCli(self):
        n = self.nodes[0]
        now = int(time.time())
        n.set("mining.forkTime=%d" % now)
        n.set("mining.forkExcessiveBlock=9000000")
        n.set("mining.forkBlockSize=3000000")
        n = self.nodes[1]
        n.set("mining.forkTime=%d" % now,"mining.forkExcessiveBlock=9000000","mining.forkBlockSize=3000000")

        # Verify that the values were properly set
        for n in self.nodes[0:2]:
            t = n.get("mining.fork*")
            assert(t['mining.forkBlockSize'] == 3000000)
            assert(t['mining.forkExcessiveBlock'] == 9000000)
            assert(t['mining.forkTime'] == now)

    def createUtxos(self,node,addrs,amt):
          wallet = node.listunspent()
          wallet.sort(key=lambda x: x["amount"],reverse=True)

          # Create a LOT of UTXOs
          logging.info("Create lots of UTXOs...")
          n=0
          group = min(100, amt)
          count = 0
          for w in wallet:
            count += group
            split_transaction(node, [w], addrs[n:group+n])
            n+=group
            if n >= len(addrs): n=0
            if count > amt:
                break
          logging.info("mine blocks")
          node.generate(1)  # mine all the created transactions
          logging.info("sync all blocks and mempools")
          self.sync_all()

    def generateTx(self, node, txBytes, addrs):
        wallet = node.listunspent()
        wallet.sort(key=lambda x: x["amount"],reverse=False)
        logging.info("Wallet length is %d" % len(wallet))

        size = 0
        count = 0
        while size < txBytes:
            count+=1
            utxo = wallet.pop()
            outp = {}
            outp[addrs[count%len(addrs)]] = utxo["amount"]
            txn = self.nodes[0].createrawtransaction([utxo], outp)
            signedtxn = self.nodes[0].signrawtransaction(txn)
            size += len(binascii.unhexlify(signedtxn["hex"]))
            self.nodes[0].sendrawtransaction(signedtxn["hex"])


    def run_test(self):
        # Creating UTXOs needed for building tx for large blocks
        NUM_ADDRS = 500
        logging.info("Creating addresses...")
        self.nodes[0].keypoolrefill(NUM_ADDRS)
        addrs = [ self.nodes[0].getnewaddress() for _ in range(NUM_ADDRS)]
        print("creating utxos")

        for j in range(0,5):
            self.createUtxos(self.nodes[0], addrs, 3000)

        self.testDefaults()
        self.testCli()  # also set up parameters on nodes 0, 1

        base = [ x.getblockcount() for x in self.nodes ]
        assert_equal(base, [base[0]] * 4)

        # TEST REQ-3: that a <= 1 MB block is rejected by the fork nodes
        # the rejection happens for the first block whose nTime is
        self.nodes[3].generate(15)

        sync_blocks(self.nodes[2:])
        sync_blocks(self.nodes[0:2])
        time.sleep(4) # even after block has synced 2, give it a little time to be denied by 0,1

        counts = [ x.getblockcount() for x in self.nodes ]
        while counts[0] != 211:
            counts = [ x.getblockcount() for x in self.nodes ]
            print(counts)
            time.sleep(1)

        assert(counts[0] < counts[2])
        assert(counts[1] < counts[3])
        assert(counts[0] == counts[1])
        assert(counts[2] == counts[3])

        # TEST that the client refuses to make a < 1MB fork block
        node = self.nodes[0]

        try:
            ret = node.generate(1)
            print(ret)
            assert(0) # should have raised exception
        except JSONRPCException as e:
            assert("bad-fork-block" in e.error["message"])


        self.nodes[2].stop()
        self.nodes[3].stop()

        # TEST REQ-3: generate a large block
        logging.info("Building > 1MB block...")

        self.generateTx(node, 1000001, addrs)
        node.set("mining.blockSize=2000000") # BUG, this should happen automatically set from forkBlockSize
        node.generate(1)

        # Test that the forked nodes accept this block as the fork block
        sync_blocks(self.nodes[0:2]) # BUG does not sync
        counts = [ x.getblockcount() for x in self.nodes ]
        print(counts)
        pdb.set_trace()

def info(type, value, tb):
   if hasattr(sys, 'ps1') or not sys.stderr.isatty():
      # we are in interactive mode or we don't have a tty-like
      # device, so we call the default hook
      sys.__excepthook__(type, value, tb)
   else:
      import traceback, pdb
      # we are NOT in interactive mode, print the exception...
      traceback.print_exception(type, value, tb)
      print
      # ...then start the debugger in post-mortem mode.
      pdb.pm()

sys.excepthook = info


def Test():
  t = BUIP055Test(True)
  bitcoinConf = {
    "debug":["net","blk","thin","mempool","req","bench","evict"], # "lck"
    "blockprioritysize":2000000  # we don't want any transactions rejected due to insufficient fees...
  }
# "--tmpdir=/ramdisk/test"
  t.main(["--tmpdir=/ramdisk/test", "--nocleanup","--noshutdown"],bitcoinConf,None) # , "--tracerpc"])
#  t.main([],bitcoinConf,None)
