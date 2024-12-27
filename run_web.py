from web_interface import app, init_db

if __name__ == '__main__':
    init_db()  # Initialize database if not exists
    app.run(host='0.0.0.0', port=5000) 