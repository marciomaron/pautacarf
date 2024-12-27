from flask import Flask, render_template
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)

def init_db():
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
                FOREIGN KEY (execution_id) REFERENCES execution_logs(id)
            )
        ''')

@app.route('/')
def dashboard():
    with sqlite3.connect('dou_scraper.db') as conn:
        conn.row_factory = sqlite3.Row
        
        # Get recent executions
        executions = conn.execute('''
            SELECT * FROM execution_logs 
            ORDER BY timestamp DESC LIMIT 50
        ''').fetchall()
        
        # Get today's matches
        today = datetime.now().strftime('%Y-%m-%d')
        matches = conn.execute('''
            SELECT m.* FROM matches m
            JOIN execution_logs e ON m.execution_id = e.id
            WHERE date(e.timestamp) = ?
        ''', (today,)).fetchall()
        
        # Calculate statistics
        stats = {
            'total_executions': len(executions),
            'successful_runs': len([e for e in executions if e['status'] == 'SUCCESS']),
            'matches_today': len(matches),
            'last_run': executions[0]['timestamp'] if executions else 'Never'
        }
        
        return render_template('dashboard.html', 
                             executions=executions, 
                             matches=matches, 
                             stats=stats)

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000) 