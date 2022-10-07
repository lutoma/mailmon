#!/usr/bin/env python3

from smtplib import SMTP
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from multiprocessing.pool import ThreadPool
from imaplib2 import IMAP4_SSL
from datetime import timedelta
import requests
import schedule
import email
import yaml
import time
import sys

text = ''
config = None


class Check:
	host = None
	imap = None
	message_id = None

	def __init__(self, host):
		self.host = host

	def __enter__(self):
		self.imap = IMAP4_SSL(self.host['host'])
		return self

	def __exit__(self, *args):
		self.imap.expunge()
		self.imap.close()
		self.imap.logout()

	def send_mail(self, to, text):
		self.message_id = make_msgid('hermes', config['source']['from_domain'])
		msg = EmailMessage()
		msg.set_content(text)
		for key, value in config['mail']['headers'].items():
			msg[key] = value

		msg.replace_header('To', msg['To'].format(addr=to))
		msg['Message-Id'] = self.message_id
		msg['Date'] = formatdate()

		with SMTP(config['source']['smtp_host'], port=587) as smtp:
			smtp.starttls()
			smtp.ehlo('hermes.localhost')
			smtp.login(config['source']['smtp_user'], config['source']['smtp_password'])
			sent = time.time()
			smtp.send_message(msg)
			smtp.quit()

		return sent

	def find_mail(self, mailbox):
		status, _ = self.imap.select(mailbox)
		if status != 'OK':
			return False

		typ, data = self.imap.search(None, 'UNSEEN')

		for num in data[0].split():
			typ, data = self.imap.fetch(num, '(RFC822)')
			msg = email.message_from_bytes(data[0][1])
			#print('have', msg['Message-Id'])
			self.imap.store(num, '+FLAGS', '\\Deleted')

			if msg['Message-Id'] == self.message_id:
				return True

		return False

	def run(self):
		status = self.imap.login(self.host['user'], self.host['password'])
		if status[0] != 'OK':
			raise Exception('Could not log in to IMAP server with provided credentials')

		start = self.send_mail(self.host['address'], text)
		attempt = 1
		success = False
		in_spam = False
		msg = f'[{self.host["name"]}] Mail did not arrive within 5 minutes'

		while True:
			if attempt > 50:
				print(f'Timeout for {self.host["name"]} after 50 attempts')
				break

			if self.find_mail('INBOX'):
				success = True
				break

			if self.find_mail('Junk') or self.find_mail('Spam'):
				success = False
				in_spam = True
				break

			backoff = max(0.3, min(attempt ** 2 * 0.01, 30))
			attempt += 1
			time.sleep(backoff)

		rtime = timedelta(seconds=time.time() - start)
		spam_msg = ' (⚠️ Marked as Spam)' if in_spam else ''
		msg = f'[{self.host["name"]}] {rtime.total_seconds()} seconds{spam_msg}'
		print(msg)

		if self.host.get('kuma_key'):
			kuma_status = 'up' if success else 'down'
			requests.get(f'{config["kuma"]["host"]}/api/push/{self.host["kuma_key"]}?status={kuma_status}&msg={msg}&ping={rtime.total_seconds()}')


def run_check(target):
	try:
		with Check(target) as check:
			return check.run()
	except Exception as e:
		print(f'Error while running check for {target["name"]}:', repr(e), file=sys.stderr)


def do_run(pool, config):
	print('Starting check run')

	try:
		snippet_res = requests.get('https://de.wikipedia.org/api/rest_v1/page/random/summary')
		extract = snippet_res.json()['extract']
	except Exception as e:
		print('Could not load wikipedia snippet: ', e, file=sys.stderr)
		extract = ''

	global text
	text = config['mail']['template'].format(snippet=extract)

	pool.map(run_check, config['targets'])


def main():
	global config

	if len(sys.argv) != 2:
		print(f'Usage: {sys.argv[0]} <config file>', file=sys.stderr)
		exit(1)

	try:
		config = yaml.safe_load(open(sys.argv[1], 'r'))
	except Exception as e:
		print('Error while reading the configuration file:', repr(e), file=sys.stderr)
		exit(1)

	with ThreadPool(processes=None) as pool:
		schedule.every(1).hour.do(do_run, pool, config)
		print('mailmon running.')

		schedule.run_pending()
		time.sleep(1)


if __name__ == '__main__':
	try:
		main()
	except KeyboardInterrupt:
		exit(0)
