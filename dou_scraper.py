import os
import pandas as pd
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import sys
import requests
from O365 import Account
from typing import List, Dict, Any
import sqlite3
import time
import re

# Import scraping-related modules
from scrapy.crawler import CrawlerRunner
from twisted.internet import reactor
from crawlDou import crawlDou
from writeResult import writeResult
import json

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def normalize_file_number(file_number: str) -> str:
    """
    Extract only numbers from a file number string.
    Example: '19515.720728/2017-36' -> '19515720728201736'
    """
    return ''.join(char for char in str(file_number) if char.isdigit())

def get_excel_data() -> List[str]:
    """
    Read file numbers from local Excel file in the 'list' folder.
    The file should be named 'list.xls' and contain a column 'NÚMERO DO PROCESSO'.
    Returns a list of file numbers to search for.
    """
    try:
        # Define path to Excel file
        file_path = os.path.join('list', 'list.xls')
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"List file not found at {file_path}")
        
        # Read XLS file - use xlrd engine for .xls files
        df = pd.read_excel(file_path, engine='xlrd')
        
        # Check if required column exists
        if 'NÚMERO DO PROCESSO' not in df.columns:
            raise ValueError("Column 'NÚMERO DO PROCESSO' not found in Excel file")
        
        # Get file numbers from column M ('NÚMERO DO PROCESSO')
        file_numbers = df['NÚMERO DO PROCESSO'].dropna().astype(str).tolist()
        
        logging.info(f"Successfully read {len(file_numbers)} file numbers from {file_path}")
        return file_numbers
        
    except Exception as e:
        logging.error(f"Error reading list file: {str(e)}")
        raise

def scrape_dou() -> List[Dict[str, Any]]:
    """
    Scrape DOU using existing crawler functionality
    Returns a list of entries found in DOU
    """
    try:
        # Configure crawler settings
        runner = CrawlerRunner({
            'USER_AGENT': 'DOU-Scraper/1.0',
            'LOG_ENABLED': True,
            'ROBOTSTXT_OBEY': True,
            'CONCURRENT_REQUESTS': 5,
            'RETRY_TIMES': 5,
            'FEEDS': {
                'items.jl': {
                    'format': 'jsonlines',
                    'encoding': 'utf8'
                }
            },
        })

        # Get today's date in the required format (DD-MM-YYYY)
        today = datetime.now().strftime('%d-%m-%Y')
        
        # Scrape all sections
        sections = ['dou1', 'dou2', 'dou3']
        results = []
        
        for section in sections:
            # Run crawler
            crawlDou(runner, today, section)
            reactor.run()
            
            # Process results
            if os.path.exists("items.jl"):
                with open("result.json", "r", encoding="utf-8") as f:
                    section_data = json.load(f)
                    for item in section_data:
                        # Extract and normalize any potential file numbers from title and content
                        title = item.get('title', '')
                        content = item.get('paragraphs', '')
                        
                        # Find potential file numbers in both title and content
                        # Look for patterns like NN.NNNNNN/NNNN-NN or similar
                        potential_numbers = re.findall(r'\d+[\.\-\/]?\d+[\.\-\/]?\d+[\.\-\/]?\d+', 
                                                     f"{title} {content}")
                        
                        normalized_numbers = [normalize_file_number(num) for num in potential_numbers]
                        
                        results.append({
                            'raw_file_numbers': potential_numbers,
                            'normalized_numbers': normalized_numbers,
                            'section': section,
                            'page': item.get('numberPage', ''),
                            'url': item.get('url', ''),
                            'content': content,
                            'title': title
                        })
                
                # Clean up temporary files
                os.remove("items.jl")
                os.remove("result.json")
                
        return results
        
    except Exception as e:
        logging.error(f"Error in DOU scraping: {str(e)}")
        raise

def send_email(matches: List[Dict[str, Any]]) -> None:
    """Send email with matches found"""
    sender_email = os.getenv('SENDER_EMAIL')
    recipient_email = os.getenv('RECIPIENT_EMAIL')
    password = os.getenv('EMAIL_PASSWORD')

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = f"DOU Matches Found - {datetime.now().strftime('%Y-%m-%d')}"

    body = "The following matches were found in today's DOU:\n\n"
    for match in matches:
        body += f"File Number: {match['file_number']}\n"
        body += f"Section: {match['section']}\n"
        body += f"Page: {match['page']}\n"
        body += f"URL: {match['url']}\n\n"

    msg.attach(MIMEText(body, 'plain'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender_email, password)
            server.send_message(msg)
        logging.info("Email sent successfully")
    except Exception as e:
        logging.error(f"Failed to send email: {str(e)}")

def create_lock_file() -> None:
    try:
        with open('dou_lock.txt', 'w') as f:
            f.write(datetime.now().strftime('%Y-%m-%d'))
        logging.info("Lock file created successfully")
    except Exception as e:
        logging.error(f"Error creating lock file: {str(e)}")
        raise

def check_lock_file() -> bool:
    try:
        with open('dou_lock.txt', 'r') as f:
            last_run = f.read().strip()
            return last_run == datetime.now().strftime('%Y-%m-%d')
    except FileNotFoundError:
        return False
    except Exception as e:
        logging.error(f"Error checking lock file: {str(e)}")
        return False

def init_db():
    """Initialize the database with required tables"""
    with sqlite3.connect('dou_scraper.db') as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                status TEXT,
                matches_found INTEGER,
                error_message TEXT,
                execution_time FLOAT
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id INTEGER,
                file_number TEXT,
                publication_date TEXT,
                section TEXT,
                page TEXT,
                url TEXT,
                FOREIGN KEY (execution_id) REFERENCES execution_logs(id)
            )
        ''')

def log_execution(status: str, matches: List[Dict[str, Any]], error_message: str = None) -> None:
    """Log execution details and matches to database"""
    execution_time = time.time() - log_execution.start_time
    
    with sqlite3.connect('dou_scraper.db') as conn:
        cursor = conn.execute('''
            INSERT INTO execution_logs 
            (timestamp, status, matches_found, error_message, execution_time)
            VALUES (?, ?, ?, ?, ?)
        ''', (datetime.now(), status, len(matches), error_message, execution_time))
        
        if matches:
            execution_id = cursor.lastrowid
            for match in matches:
                conn.execute('''
                    INSERT INTO matches 
                    (execution_id, file_number, section, page, url)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    execution_id,
                    match['file_number'],
                    match['section'],
                    match['page'],
                    match['url']
                ))

# Add this at the start of the script to track execution time
log_execution.start_time = time.time()

def main():
    try:
        # Add this line at the start of main()
        logging.info("Starting DOU scraper...")
        
        # Initialize database
        init_db()
        logging.info("Database initialized")
        
        # Get search terms from Excel and normalize them
        search_terms = get_excel_data()
        normalized_search_terms = [normalize_file_number(term) for term in search_terms]
        logging.info(f"Found {len(search_terms)} terms to search for")
        
        # Scrape DOU
        dou_entries = scrape_dou()
        logging.info(f"Scraped {len(dou_entries)} entries from DOU")
        
        # Find matches using normalized numbers
        matches = []
        for entry in dou_entries:
            for norm_number in entry['normalized_numbers']:
                if norm_number in normalized_search_terms:
                    original_format = next(
                        num for i, num in enumerate(entry['raw_file_numbers'])
                        if normalize_file_number(num) == norm_number
                    )
                    matches.append({
                        'file_number': original_format,
                        'section': entry['section'],
                        'page': entry['page'],
                        'url': entry['url'],
                        'title': entry['title']
                    })
                    break
        
        # Log execution and handle matches
        if matches:
            logging.info(f"Found {len(matches)} matches")
            send_email(matches)
            log_execution('SUCCESS', matches)
            sys.exit(1)
        
        logging.info("No matches found")
        log_execution('SUCCESS', [])
        sys.exit(0)
            
    except Exception as e:
        error_msg = str(e)
        logging.error(f"Error in main execution: {error_msg}")
        log_execution('ERROR', [], error_msg)
        sys.exit(2)

if __name__ == "__main__":
    main() 