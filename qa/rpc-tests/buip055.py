#!/usr/bin/env python3
# Copyright (c) 2015-2017 The Bitcoin Unlimited developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

import time
import shutil
import random
from binascii import hexlify
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal
from test_framework.util import *
from test_framework.script import *
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
        return now

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

    def wastefulOutput(self, btcAddress):
        data = b"""this is junk data. this is junk data. this is junk data. this is junk data. this is junk data.
this is junk data. this is junk data. this is junk data. this is junk data. this is junk data.
this is junk data. this is junk data. this is junk data. this is junk data. this is junk data."""
        ret = CScript([OP_PUSHDATA1, len(data), data, OP_DROP, OP_DUP, OP_HASH160, decodeBase58(btcAddress), OP_EQUALVERIFY, OP_CHECKSIG])
        return ret

    def generateTx(self, node, txBytes, addrs):
        wallet = node.listunspent()
        wallet.sort(key=lambda x: x["amount"],reverse=False)
        logging.info("Wallet length is %d" % len(wallet))

        size = 0
        count = 0
        decContext = decimal.getcontext().prec
        decimal.getcontext().prec = 8 + 8 # 8 digits to get to 21million, and each bitcoin is 100 million satoshis
        while size < txBytes:
            count+=1
            utxo = wallet.pop()
            outp = {}
            payamt = satoshi_round(utxo["amount"]/decimal.Decimal(8.0))  # Make the tx bigger by adding addtl outputs so it validates faster
            for x in range(0,8):
                outp[addrs[(count+x)%len(addrs)]] = payamt  # its test code, I don't care if rounding error is folded into the fee
                #outscript = self.wastefulOutput(addrs[(count+x)%len(addrs)])
                #outscripthex = hexlify(outscript).decode("ascii")
                #outp[outscripthex] = payamt
            outp["data"] ='54686973206973203830206279746573206f6620746573742064617461206372656174656420746f20757365207570207472616e73616374696f6e20737061636520666173746572202e2e2e2e2e2e2e'
            txn = node.createrawtransaction([utxo], outp)
            signedtxn = node.signrawtransaction(txn)
            size += len(binascii.unhexlify(signedtxn["hex"]))
            node.sendrawtransaction(signedtxn["hex"])
        logging.info("%d tx %d length" % (count,size))
        decimal.getcontext().prec = decContext



    def run_test(self):
        # Creating UTXOs needed for building tx for large blocks
        NUM_ADDRS = 500
        logging.info("Creating addresses...")
        self.nodes[0].keypoolrefill(NUM_ADDRS)
        addrs = [ self.nodes[0].getnewaddress() for _ in range(NUM_ADDRS)]
        logging.info("creating utxos")

        for j in range(0,5):
            self.createUtxos(self.nodes[0], addrs, 3000)

        sync_blocks(self.nodes)

        self.testDefaults()
        forkTime = self.testCli()  # also sets up parameters on nodes 0, 1 to to fork

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
            logging.info(counts)
            time.sleep(1)

        assert(counts[0] < counts[2])
        assert(counts[1] < counts[3])
        assert(counts[0] == counts[1])
        assert(counts[2] == counts[3])

        # TEST that the client refuses to make a < 1MB fork block
        node = self.nodes[0]

        try:
            ret = node.generate(1)
            logging.info(ret)
            assert(0) # should have raised exception
        except JSONRPCException as e:
            assert("bad-blk-too-small" in e.error["message"])


        # self.nodes[2].stop()
        # self.nodes[3].stop()

        # TEST REQ-3: generate a large block
        logging.info("Building > 1MB block...")

        self.generateTx(node, 1005000, addrs)
        # if we don't sync mempools, when a block is created the system will be so busy syncing tx that it will time out
        # requesting the block, and so never receive it.
        # This only happens in testnet because there is only 1 node generating all the tx and with the block.
        sync_mempools(self.nodes[0:2],wait=10)

        commonAncestor = node.getbestblockhash()
        node.generate(1)
        forkHeight = node.getblockcount()

        # Test that the forked nodes accept this block as the fork block
        sync_blocks(self.nodes[0:2])
        # counts = [ x.getblockcount() for x in self.nodes[0:2] ]
        counts = [ x.getblockcount() for x in self.nodes ]
        logging.info(counts)

        # generate blocks and ensure that the other node syncs them
        self.nodes[1].generate(3)
        sync_blocks(self.nodes[0:2])
        self.nodes[0].generate(3)
        sync_blocks(self.nodes[0:2])

        # generate blocks on the original side
        self.nodes[2].generate(3)
        sync_blocks(self.nodes[2:])
        counts = [ x.getblockcount() for x in self.nodes ]
        assert(counts == [218, 218, 223, 223])
        forkBest = self.nodes[0].getbestblockhash()
        origBest = self.nodes[3].getbestblockhash()
        logging.info("Fork height: %d" % forkHeight)
        logging.info("Common ancestor: %s" % commonAncestor)
        logging.info("Fork tip: %s" % forkBest)
        logging.info("Small block tip: %s" % origBest)

        # Limitation: fork logic won't cause a re-org if the node is beyond it
        stop_node(self.nodes[2],2)
        self.nodes[2]=start_node(2, self.options.tmpdir, ["-debug", "-mining.forkTime=%d" % forkTime, "-mining.forkExcessiveBlock=9000000", "-mining.forkBlockSize=3000000"], timewait=900)
        connect_nodes(self.nodes[2],3)
        connect_nodes(self.nodes[2],0)
        sync_blocks(self.nodes[0:2])
        assert(self.nodes[2].getbestblockhash() == origBest)

        # Now clean up the node to force a re-sync, but connect to the small block fork nodes
        stop_node(self.nodes[2],2)
        shutil.rmtree(self.options.tmpdir + os.sep + "node2" + os.sep + "regtest")
        self.nodes[2]=start_node(2, self.options.tmpdir, ["-debug", "-mining.forkTime=%d" % forkTime, "-mining.forkExcessiveBlock=9000000", "-mining.forkBlockSize=3000000"], timewait=900)
        connect_nodes(self.nodes[2],3)
        time.sleep(10) # I have to sleep here because I'm not expecting the nodes to sync
        t = self.nodes[2].getinfo()
        assert(t["blocks"] == forkHeight-1)  # Cannot progress beyond the common ancestor, because we are looking for a big block
        # TODO now connect to fork node to see it continue to sync

        # test full sync if only connected to forked nodes
        stop_node(self.nodes[2],2)
        logging.info("Resync to minority fork connected to minority fork nodes only")

        shutil.rmtree(self.options.tmpdir + os.sep + "node2" + os.sep + "regtest")
        self.nodes[2]=start_node(2, self.options.tmpdir, ["-debug", "-mining.forkTime=%d" % forkTime, "-mining.forkExcessiveBlock=9000000", "-mining.forkBlockSize=3000000"], timewait=900)
        connect_nodes(self.nodes[2],0)
        sync_blocks(self.nodes[0:3])
        t = self.nodes[2].getinfo()
        assert(self.nodes[2].getbestblockhash() == forkBest)

        # Now clean up the node to force a re-sync, but connect to both forks to prove it follows the proper fork
        stop_node(self.nodes[2],2)
        logging.info("Resync to minority fork in the presence of majority fork nodes")
        shutil.rmtree(self.options.tmpdir + os.sep + "node2" + os.sep + "regtest")
        self.nodes[2]=start_node(2, self.options.tmpdir, ["-debug", "-mining.forkTime=%d" % forkTime, "-mining.forkExcessiveBlock=9000000", "-mining.forkBlockSize=3000000"], timewait=900)
        connect_nodes(self.nodes[2],3)
        connect_nodes(self.nodes[2],0)
        sync_blocks(self.nodes[0:3])

        assert(self.nodes[2].getbestblockhash() == forkBest)
        #pdb.set_trace()

        logging.info("Reindex across fork")
        # see if we reindex properly across the fork
        node = self.nodes[2]
        curCount = node.getblockcount()
        stop_node(node,2)
        node = self.nodes[2]=start_node(2, self.options.tmpdir, ["-debug", "-reindex", "-checkblockindex=1", "-mining.forkTime=%d" % forkTime, "-mining.forkExcessiveBlock=9000000", "-mining.forkBlockSize=3000000"], timewait=900)
        time.sleep(10)
        assert_equal(node.getblockcount(), curCount)


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
