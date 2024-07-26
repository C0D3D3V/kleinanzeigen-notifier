#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script Name:     kleinanzeigen_notifier.py
Author:          Daniel Vogt
Date:            2024-07-18
Description:     Dieses Skript überwacht Kleinanzeigen auf neue Einträge
                 basierend auf vordefinierten Jobs und sendet Benachrichtigungen
                 per E-Mail, wenn neue relevante Anzeigen gefunden werden.
Version:         1.0
License:         MIT License
"""

import asyncio
import json
import logging
import os
import random
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup


@dataclass
class Article:
    id: str
    title: str
    description: str


def load_environment_variables():
    variables = [
        "KN_PATH",
        "KN_INTERVAL",
        "KN_SMTP_HOST",
        "KN_SMTP_PORT",
        "KN_SMTP_SECURE",
        "KN_SMTP_USER",
        "KN_SMTP_PASS",
        "KN_SMTP_FROM_ADDRESS",
        "KN_SMTP_HOSTNAME",
        "KN_TEST_EMAIL",
        "KN_TEST_EMAIL_TO_ADDRESS",
        "KN_PARALLEL_DOWNLOADS",
    ]
    config = {}
    for var in variables:
        value = os.getenv(var)
        if not value:
            raise EnvironmentError(f"Environment variable {var} is not set.")
        config[var] = value
    return config


def parse_interval(interval_str):
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return int(interval_str[:-1]) * units[interval_str[-1]]


def send_email_msg(config, to_address: str, message: str):
    try:
        if config["KN_SMTP_SECURE"].lower() in ["true", "1"]:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(config["KN_SMTP_HOST"], config["KN_SMTP_PORT"], context=context) as server:
                server.login(config["KN_SMTP_USER"], config["KN_SMTP_PASS"])
                server.sendmail(config["KN_SMTP_FROM_ADDRESS"], to_address, message)
        else:
            with smtplib.SMTP(config["KN_SMTP_HOST"], config["KN_SMTP_PORT"]) as server:
                server.starttls()
                server.login(config["KN_SMTP_USER"], config["KN_SMTP_PASS"])
                server.sendmail(config["KN_SMTP_FROM_ADDRESS"], to_address, message)
        logging.info("Email sent successfully to %s.", to_address)
    except Exception as e:
        logging.error("Failed to send email: %s", e)


def send_test_email(config):
    message = MIMEMultipart("alternative")
    message["Subject"] = "Test Email"
    message["From"] = config["KN_SMTP_FROM_ADDRESS"]
    message["To"] = config["KN_TEST_EMAIL_TO_ADDRESS"]
    text = "This is a test email."
    part = MIMEText(text, "plain")
    message.attach(part)

    send_email_msg(config, config["KN_TEST_EMAIL_TO_ADDRESS"], message.as_string())


def load_or_create_jobs_json(config):
    jobs_path = Path(config["KN_PATH"]) / "jobs.json"
    if not jobs_path.exists():
        example_job = {
            "tracking_url": "https://www.kleinanzeigen.de/s-zu-verschenken-tauschen/77746/k%C3%BCche/k0c272l9032r30",
            "title": "Küche zu verschenken",
            "email": "example@example.com",
            "blacklist_words": ["skip"],
            "blacklist_texts": ["do not match any article, with one of these texts"],
            "whitelist_words": ["onlywiththis"],
            "whitelist_texts": ["only match article, with one of these texts"],
            "job_id": str(random.randint(100000000000, 999999999999)),
        }
        logging.error('No jobs.json could be loaded')
        logging.info('Example jobs.json:')
        logging.info(json.dumps([example_job], indent=2))
        time.sleep(5)
        return None
    try:
        with open(jobs_path, "r", encoding='utf-8') as f:
            jobs = json.load(f)
            if not isinstance(jobs, list):
                jobs = [jobs]
            keys_to_check = ["blacklist_words", "blacklist_texts", "whitelist_words", "whitelist_texts"]
            for job in jobs:
                if "job_id" not in job:
                    job["job_id"] = str(random.randint(100000000000, 999999999999))
                for key in keys_to_check:
                    if key not in job:
                        job[key] = []
                    else:
                        job[key] = [s.lower() for s in job[key]]

        with open(jobs_path, "w", encoding='utf-8') as f:
            json.dump(jobs, f, indent=2)
        return jobs
    except Exception as e:
        logging.error("Error loading jobs.json: %s", e)
        time.sleep(5)
        return None


def load_or_create_job_json(config, job_id):
    job_json_path = Path(config["KN_PATH"]) / f"{job_id}.json"
    if job_json_path.exists():
        try:
            with open(job_json_path, "r", encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {"ads": []}
    return {"ads": []}


async def fetch_article(ad_id, job, pool):
    ad_url = f"https://www.kleinanzeigen.de/s-anzeige/{ad_id}"
    ad_content = await pool.fetch(ad_url)
    ad_soup = BeautifulSoup(ad_content, "html.parser")
    title_element = ad_soup.find("h1", {"id": "viewad-title"})
    title = title_element.get_text(strip=True)
    description_element = ad_soup.find("p", {"id": "viewad-description-text"})
    description = description_element.get_text(strip=True)

    title_lower = title.lower()
    description_lower = description.lower()

    # Blacklist filter
    if job.get("blacklist_texts"):
        if any(bl_word in title_lower or bl_word in description_lower for bl_word in job["blacklist_texts"]):
            return None

    title_words = set(title_lower.split('\n\r \t,.!?"§$%&/(){}[]?\\'))
    description_words = set(description_lower.split('\n\r \t,.!?"§$%&/(){}[]?\\'))
    if job.get("blacklist_words"):
        if any(bl_word in title_words or bl_word in description_words for bl_word in job["blacklist_words"]):
            return None

    # Whitelist filter
    if job.get("whitelist_texts") and len(job["whitelist_texts"]) > 0:
        if not any(wl_text in title_lower or wl_text in description_lower for wl_text in job["whitelist_texts"]):
            return None

    if job.get("whitelist_words") and len(job["whitelist_words"]) > 0:
        if not any(wl_word in title_words or wl_word in description_words for wl_word in job["whitelist_words"]):
            return None

    return Article(id=ad_id, title=title, description=description)


async def process_job(config, job, pool):
    job_data = load_or_create_job_json(config, job["job_id"])
    new_ads = []

    page_url = job["tracking_url"]
    while page_url:
        page_content = await pool.fetch(page_url)
        soup = BeautifulSoup(page_content, "html.parser")
        ad_table = soup.find("ul", {"id": "srchrslt-adtable"})
        if not ad_table:
            break

        for ad_item in ad_table.find_all("article", {"class": "aditem"}):
            ad_id = ad_item.get("data-adid")
            if not ad_id or ad_id in job_data["ads"]:
                break
            new_ads.append(ad_id)

        next_page = soup.find("a", {"class": "pagination-next"})
        page_url = next_page["href"] if next_page else None

    tasks = [fetch_article(ad_id, job, pool) for ad_id in new_ads]
    articles = await asyncio.gather(*tasks)
    articles = [article for article in articles if article is not None]

    if articles:
        send_email(config, job, articles)

    job_data["ads"].extend(new_ads)
    job_json_path = Path(config["KN_PATH"]) / f"{job['job_id']}.json"
    with open(job_json_path, "w", encoding='utf-8') as f:
        json.dump(job_data, f, indent=2)


def send_email(config, job, articles):
    message = MIMEMultipart("alternative")
    message["Subject"] = job["title"]
    message["From"] = config["KN_SMTP_FROM_ADDRESS"]
    message["To"] = job["email"]

    html = "<html><body>"
    html += f"<h1>{job['title']}</h1>"
    for article in articles:
        url = f"https://www.kleinanzeigen.de/s-anzeige/{article.id}"
        html += f'<p><a href="{url}">{article.title}</a><br>{article.description}</p>'
    html += "</body></html>"

    part = MIMEText(html, "html")
    message.attach(part)

    send_email_msg(config, job['email'], message.as_string())


class Worker:
    def __init__(self):
        self.session = aiohttp.ClientSession()

    async def close(self):
        await self.session.close()

    async def fetch(self, url: str) -> str:
        async with self.session.get(url) as response:
            return await response.text()


class WorkerPool:
    def __init__(self, num_workers: int):
        self.num_workers = num_workers
        self.workers = [Worker() for _ in range(num_workers)]
        self.queue: asyncio.Queue[Worker] = asyncio.Queue()

    async def start_workers(self):
        for worker in self.workers:
            await self.queue.put(worker)

    async def stop_workers(self):
        for worker in self.workers:
            await worker.close()

    async def get_worker(self) -> Worker:
        return await self.queue.get()

    async def release_worker(self, worker: Worker):
        await self.queue.put(worker)

    async def fetch(self, url: str) -> str:
        worker = await self.get_worker()
        try:
            result = await worker.fetch(url)
        finally:
            await self.release_worker(worker)
        return result


async def process_all_jobs(config):
    jobs = None
    while not jobs:
        jobs = load_or_create_jobs_json(config)

    pool = WorkerPool(int(config["KN_PARALLEL_DOWNLOADS"]))
    await pool.start_workers()

    tasks = [process_job(config, job, pool) for job in jobs]
    await asyncio.gather(*tasks)

    await pool.stop_workers()


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Kleinanzeigen-Notifier started")

    config = load_environment_variables()

    if config["KN_TEST_EMAIL"].lower() in ["true", "1"]:
        send_test_email(config)

    interval_seconds = parse_interval(config["KN_INTERVAL"])

    while True:
        try:
            asyncio.run(process_all_jobs(config))
        except Exception as e:
            logging.error("Error during processing: %s", e)
        logging.info("Sleeping now for %s", config["KN_INTERVAL"])
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
