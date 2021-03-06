# pyncoin/pychain.py

import hashlib
from datetime import datetime, timezone
from decimal import Decimal

from bitstring import BitArray

from transaction import Transaction, TxOut
from utils import RawSerializable, hex_to_bytes, bytes_to_hex
from utils import BadRequestError, NotFoundError

''' Implements the business logic of the blockchain. '''

class Block(RawSerializable):
    ''' Represents a block in the blockchain. A block can contain arbitrary data
    in the format of a unicode string. '''

    INT_SIZE = 8
    BYTE_ORDER = 'big'

    def __init__(self, index, previous_hash, timestamp, data, difficulty, nonce):
        '''Initializes the block.
        Params:
            - index (int): The height of the block in the blockchain
            - previous_hash (bytes): A reference to the hash of the previous block. 
                This value explicitly defines the previous block.
            - timestamp (datetime): A timestamp
            - data (list<Transaction>): The list of transactions to be included in the block
            - difficulty (int): The difficulty of the Proof of Work algorithm
            - nonce (int): The nonce of the block
        '''
        self.index = index
        self.previous_hash = previous_hash
        self.timestamp = timestamp
        self.data = data
        self.difficulty = difficulty
        self.nonce = nonce
        self.hash = self.calculate_hash_for_block()

    def __eq__(self, other):
        if isinstance(self, other.__class__):
            return self.__dict__ == other.__dict__
        return False

    @staticmethod
    def calculate_hash(index, previous_hash, timestamp, data, difficulty, nonce):
        hasher = hashlib.sha256()
        hasher.update(index.to_bytes(Block.INT_SIZE, byteorder=Block.BYTE_ORDER))
        if previous_hash is not None:
            hasher.update(previous_hash)
        ts_int = int(timestamp.timestamp())
        hasher.update(ts_int.to_bytes(Block.INT_SIZE, byteorder=Block.BYTE_ORDER))
        if isinstance(data, list):
            for tx in data:
                hasher.update(tx.get_id())
        else:
            hasher.update(repr(data).encode('utf-8'))
        hasher.update(difficulty.to_bytes(Block.INT_SIZE, byteorder=Block.BYTE_ORDER))
        hasher.update(nonce.to_bytes(Block.INT_SIZE, byteorder=Block.BYTE_ORDER))
        return hasher.digest()

    def calculate_hash_for_block(self):
        return Block.calculate_hash(self.index, self.previous_hash, self.timestamp, 
                                    self.data, self.difficulty, self.nonce)

    @staticmethod
    def find(index, previous_hash, timestamp, data, difficulty):
        nonce = 0
        while True:
            hash = Block.calculate_hash(index, previous_hash, timestamp, data, difficulty, nonce)
            if Block.hash_matches_difficulty(hash, difficulty):
                return Block(index, previous_hash, timestamp, data, difficulty, nonce)
            nonce += 1

    @staticmethod
    def genesis_block():
        timestamp = datetime.fromtimestamp(1528359030, tz=timezone.utc)
        return Block(0, None, timestamp, [], 0, 0)

    @staticmethod
    def hash_matches_difficulty(hash, difficulty):
        bits = BitArray(bytes=hash)
        required_prefix = '0' * difficulty
        return bits.bin.startswith(required_prefix)

    def has_valid_hash(self):
        if self.calculate_hash_for_block() != self.hash:
            print('invalid hash')
            return False
        elif not Block.hash_matches_difficulty(self.hash, self.difficulty):
            print('block difficulty not satisfied. Expected: {}, got: {}'.format(self.difficulty, self.hash))
            return False
        return True

    @staticmethod
    def is_genesis(block):
        return block == Block.genesis_block()

    def is_valid_next(self, next_block):
        if not next_block.has_valid_structure():
            print('invalid structure')
            return False
        elif self.index + 1 != next_block.index:
            print('invalid index')
            return False
        elif self.hash != next_block.previous_hash:
            print('invalid previous hash')
            return False
        elif not Block.is_valid_timestamp(next_block, self):
            print('invalid timestamp')
            return False
        elif not next_block.has_valid_hash():
            return False
        return True

    def to_raw(self):
        return {
            'index': self.index,
            'previousHash': self.previous_hash.hex() if self.previous_hash is not None else None,
            'timestamp': int(self.timestamp.timestamp()),
            'data': Transaction.to_raw_list(self.data),
            'difficulty': self.difficulty,
            'nonce': self.nonce,
            'hash': self.hash.hex()
        }

    @classmethod
    def from_raw(cls, raw_obj):
        index = raw_obj['index']
        previous_hash = hex_to_bytes(raw_obj['previousHash']) if raw_obj['previousHash'] is not None else None
        timestamp = datetime.fromtimestamp(raw_obj['timestamp'], tz=timezone.utc)
        data = Transaction.from_raw_list(raw_obj['data'])
        difficulty = raw_obj['difficulty']
        nonce = raw_obj['nonce']
        return cls(index=index, previous_hash=previous_hash, timestamp=timestamp, 
                   data=data, difficulty=difficulty, nonce=nonce)

    def has_valid_structure(self):
        return (isinstance(self.index, int) 
            and isinstance(self.hash, bytes) 
            and (isinstance(self.previous_hash, bytes) if self.previous_hash is not None else True)
            and isinstance(self.timestamp, datetime) 
            and isinstance(self.data, list)
            and all([isinstance(tx, Transaction) for tx in self.data])
            and isinstance(self.difficulty, int)
            and isinstance(self.nonce, int))

    @staticmethod
    def is_valid_timestamp(new_block, previous_block):
        return ((previous_block.timestamp - new_block.timestamp).total_seconds() < 60 
            and (new_block.timestamp - datetime.now(tz=timezone.utc)).total_seconds() < 60)

class Blockchain(RawSerializable):

    BLOCK_GENERATION_INTERVAL = 10 # in seconds
    DIFFICULTY_ADJUSTMENT_INTERVAL = 10 # in blocks

    def __init__(self, tx_pool):
        self.blocks = [Block.genesis_block()]
        self.p2p_application = None
        self.tx_pool = tx_pool
        self.unspent_tx_outs = []

    def get_latest(self):
        return self.blocks[-1]

    @staticmethod
    def validate_blocks(blocks):
        if not isinstance(blocks, list):
            print('blocks argument is not a list')
            return None
        elif not Block.is_genesis(blocks[0]):
            print('invalid genesis block')
            return None
        unspent_tx_outs = []
        for i, block in enumerate(blocks):
            if not isinstance(blocks[i], Block) or i != 0 and not blocks[i - 1].is_valid_next(block):
                print('block #{} is not valid'.format(i))
                return None
            unspent_tx_outs = Transaction.process_transactions(block.data, unspent_tx_outs, block.index)
            if unspent_tx_outs is None:
                print('invalid transactions in blockchain')
                return None
        return unspent_tx_outs

    @staticmethod
    def get_accumulated_difficulty(blocks):
        return sum([2 ** block.difficulty for block in blocks])

    def add_block(self, block):
        if not isinstance(block, Block):
            raise BadRequestError('invalid block', payload=block.to_raw())
        if not self.get_latest().is_valid_next(block):
            return False
        unspent_tx_outs = Transaction.process_transactions(block.data, self.unspent_tx_outs, block.index)
        if unspent_tx_outs is None:
            print('block is not valid in terms of transactions')
            return False
        self.blocks.append(block)
        self.unspent_tx_outs = unspent_tx_outs
        self.tx_pool.update(unspent_tx_outs)
        return True

    def generate_raw_next_block(self, data):
        previous_block = self.get_latest()
        next_index = previous_block.index + 1
        next_timestamp = datetime.now(tz=timezone.utc)
        difficulty = self.get_difficulty()
        print('Blockchain.generate_next: difficulty = {}'.format(difficulty))
        next_block = Block.find(next_index, previous_block.hash, next_timestamp, data, difficulty)
        if self.add_block(next_block):
            self.broadcast_latest()
            return next_block
        else:
            return None

    def generate_next_block(self, wallet):
        coinbase_tx = Transaction.coinbase(wallet.get_public_key(), self.get_latest().index + 1)
        block_data = [coinbase_tx] + self.tx_pool.transactions
        print('block_data: {}'.format(block_data))
        return self.generate_raw_next_block(block_data)

    def generate_next_with_transaction(self, wallet, receiver_address, amount):
        if not TxOut.is_valid_address(receiver_address):
            error_payload = {'address': bytes_to_hex(receiver_address)}
            raise BadRequestError('invalid address', payload=error_payload)
        if not isinstance(amount, Decimal):
            error_payload = {'amount': amount}
            raise BadRequestError('invalid amount', payload=error_payload)
        coinbase_tx = Transaction.coinbase(wallet.get_public_key(), self.get_latest().index + 1)
        tx = wallet.create_transaction(receiver_address, amount, self.unspent_tx_outs, self.tx_pool)
        block_data = [coinbase_tx, tx]
        return self.generate_raw_next_block(block_data)

    def send_transaction(self, wallet, receiver_address, amount):
        tx = wallet.create_transaction(receiver_address, amount, self.unspent_tx_outs, self.tx_pool)
        if self.tx_pool.add_transaction(tx, self.unspent_tx_outs):
            self.broadcast_transaction_pool()
        else:
            raise BadRequestError('invalid transaction or transaction is already in the pool')
        return tx

    def unspent_tx_outs_for_address(self, address):
        return [uTxO for uTxO in self.unspent_tx_outs if uTxO.address == address]

    def my_unspent_tx_outs(self, wallet):
        return self.unspent_tx_outs_for_address(wallet.get_public_key())

    def handle_received_transaction(self, transaction):
        return self.tx_pool.add_transaction(transaction, self.unspent_tx_outs)

    def get_balance(self, wallet):
        return wallet.get_balance(self.unspent_tx_outs)

    def broadcast_latest(self):
        self.p2p_application.broadcast_latest(self)

    def broadcast_transaction_pool(self):
        self.p2p_application.broadcast_transaction_pool(self.tx_pool)

    def get_block_with_hash(self, hash):
        block = next((block for block in self.blocks if block.hash == hash), None)
        if not block:
            raise NotFoundError('block not found', {'hash': bytes_to_hex(hash)})
        return block

    def get_transaction_with_id(self, transaction_id):
        transaction = next((tx for block in self.blocks for tx in block.data if tx.id == transaction_id), None)
        if not transaction:
            raise NotFoundError('transaction not found', {'id': bytes_to_hex(transaction_id)})
        return transaction

    def replace(self, new_blocks):
        unspent_tx_outs = Blockchain.validate_blocks(new_blocks)
        valid_chain = unspent_tx_outs is not None
        if (isinstance(new_blocks, list)
            and valid_chain
            and Blockchain.get_accumulated_difficulty(new_blocks) > Blockchain.get_accumulated_difficulty(self.blocks)):
            print('Received blockchain is valid. Replacing current blockchain with received blockchain.')
            self.blocks = new_blocks
            self.unspent_tx_outs = unspent_tx_outs
            self.tx_pool.update(unspent_tx_outs)
            self.broadcast_latest()
            return True
        else:
            print('Received blockchain is invalid.')
            return False

    def to_raw(self):
        return Block.to_raw_list(self.blocks)

    @classmethod
    def from_raw(cls, raw_obj):
        raise AssertionError('Blockchain can not be constructed from raw objects.')

    def get_difficulty(self):
        latest_block = self.get_latest()
        if latest_block.index % Blockchain.DIFFICULTY_ADJUSTMENT_INTERVAL == 0 and latest_block.index != 0:
            return self.get_adjusted_difficulty()
        else:
            return latest_block.difficulty

    def get_adjusted_difficulty(self):
        prev_adjusment_block = self.blocks[max(0, len(self.blocks) - Blockchain.DIFFICULTY_ADJUSTMENT_INTERVAL)]
        latest_block = self.get_latest()
        time_expected = Blockchain.BLOCK_GENERATION_INTERVAL * Blockchain.DIFFICULTY_ADJUSTMENT_INTERVAL
        time_taken = (latest_block.timestamp - prev_adjusment_block.timestamp).total_seconds()
        print('prev_adjusment_block.idx: {}, latest_block.idx: {}'.format(prev_adjusment_block.index, latest_block.index))
        print('time_taken: {}, time_expected: {}'.format(time_taken, time_expected))
        if time_taken < time_expected / 2:
            return prev_adjusment_block.difficulty + 1
        elif time_taken > time_expected * 2:
            return max(prev_adjusment_block.difficulty - 1, 0)
        else:
            return prev_adjusment_block.difficulty
