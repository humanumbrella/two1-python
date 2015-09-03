from collections import namedtuple
import json
import click
from two1.config import pass_config
from two1.bitcoin.block import CompactBlock
from two1.bitcoin.txn import Transaction
import time
import random
from two1.lib import rest_client, message_factory, login
import two1.config as cmd_config
from two1.bitcoin.hash import Hash
from two1.uxstring import UxString
import two1.bitcoin.utils as utils

from two1.gen import swirl_pb2 as swirl


@click.command()
@pass_config
def mine(config):
    """Fastest way to get Bitcoin!"""
    # detect if hat is present
    bitcoinkit_present = False
    config.log("\nMining...")

    if bitcoinkit_present:
        # do minertop
        pass
    else:
        rest_client = rest_client.TwentyOneRestClient(cmd_config.TWO1_HOST,
                                                        login.get_auth_key())

        payout_address = config.wallet.current_address()
        config.log("Setting payout_address to {}".format(payout_address))
        # set a new address from the HD wallet for payouts
        rest_client.account_payout_address_post(config.username,payout_address)

        work_msg = mining_rest_client.get_work(username=config.username)
        msg_factory = message_factory.SwirlMessageFactory()
        work = msg_factory.read_object(work_msg.content)
        share = find_valid_nonce(config, work)

        message_id = random.randint(1, 1e5)
        req_msg = msg_factory.create_submit_request(message_id=message_id,
                                                    work_id=work.work_id,
                                                    enonce2=share.enonce2,
                                                    otime=share.otime,
                                                    nonce=share.nonce)

        client_message = swirl.SwirlClientMessage()
        reqq = req_msg[2:]
        client_message.ParseFromString(reqq)
        # take a look at the protobuf file to see what this means.
        message_type = client_message.WhichOneof("clientmessages")
        msg = getattr(client_message, message_type)
        mining_rest_client.send_work(username=config.username, data=req_msg)

        if payment_result.status_code != 200 or not hasattr(payment_result, "text"):
            click.echo(UxString.Error.server_err)
            return

        config.log("Mining Complete")
        payment_details = json.loads(payment_result.text)
        satoshi = payment_details["amount"]
        config.log("You mined {} ฿\n".format(satoshi), fg="yellow")
        try:
            bitcoin_address = config.wallet.current_address()
        except AttributeError:
            bitcoin_address = "Not Set"

        config.log("Setting your payout address to {}\n".format(payout_address))
        balance_c = config.wallet.confirmed_balance()
        balance_u = config.wallet.unconfirmed_balance() + satoshi
        config.log('''Wallet''', fg='magenta')
        config.log('''\
    Balance (confirmed)   : {} Satoshi
    Balance (unconfirmed) : {} Satoshi
    Payout Address        : {}
'''
                   .format(balance_c, balance_u, bitcoin_address)
                   )


def get_work(config, client):
    username = config.username
    work_msg = client.get_work(username=username)
    if work_msg.status_code == 200:
        msg_factory = message_factory.SwirlMessageFactory()
        work = msg_factory.read_object(work_msg.content)
        return work
    elif work_msg.status_code == 400:
        click.echo(UxString.Error.non_existing_user % username)
        click.echo(UxString.enter_username_retry)
        login.create_username(config=config, username=None)
    else:
        click.echo(UxString.Error.server_err)


Share = namedtuple('Share', ['enonce2', 'nonce', 'otime', 'work_id'])
Work = namedtuple('Work', ['work_id', 'enonce2', 'cb'])


def mine_work(work_msg, username):
    enonce1, enonce2_size = get_enonces(username=username)

    pool_target = utils.bits_to_target(work_msg.bits_pool)
    for enonce2_num in range(0, 2 ** (enonce2_size * 8)):
        enonce2 = enonce2_num.to_bytes(enonce2_size, byteorder="big")

        cb_txn, _ = Transaction.from_bytes(
            work_msg.coinb1 + enonce1 + enonce2 + work_msg.coinb2)
        cb = CompactBlock(work_msg.height,
                          work_msg.version,
                          Hash(work_msg.prev_block_hash),
                          work_msg.ntime,
                          work_msg.nbits,  # lower difficulty work for testing
                          work_msg.merkle_edge,
                          cb_txn)

        row_counter = 0
        for nonce in range(0xffffffff):

            if nonce % 6e3 == 0:
                click.echo(click.style(u'█', fg='green'), nl=False)
                row_counter += 1
            if row_counter > 40:
                row_counter = 0
                click.echo("")

            cb.block_header.nonce = nonce
            h = cb.block_header.hash.to_int('little')
            if h < pool_target:
                share = Share(
                    enonce2=enonce2,
                    nonce=nonce,
                    work_id=work_msg.work_id,
                    otime=int(time.time()))
                # adds a new line at the end of progress bar
                click.echo("")
                return share

        click.echo("Exhausted enonce1 space. Changing enonce2")

def get_enonces(username):
    enonce1_size = 8
    enonce1 = username[-1 * enonce1_size:].encode()
    if len(enonce1) != enonce1_size:
        enonce1 = enonce1 + ((enonce1_size - len(enonce1)) * b"0")
    enonce2_size = 4
    return enonce1, enonce2_size


def save_work(client, share, username):
    message_id = random.randint(1, 1e5)
    msg_factory = message_factory.SwirlMessageFactory()
    req_msg = msg_factory.create_submit_share_request(message_id=message_id,
                                                      work_id=share.work_id,
                                                      enonce2=share.enonce2,
                                                      otime=share.otime,
                                                      nonce=share.nonce)

    return client.send_work(username=username, data=req_msg)
