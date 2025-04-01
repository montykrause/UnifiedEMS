from flask import Flask, request, render_template, redirect, url_for, session
import psycopg2
import bcrypt

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Replace with a strong, random key

# Database connection function
def get_db_connection():
    conn = psycopg2.connect(
        dbname="unifiedems",
        user="postgres",
        password="11928240@mK",  # Replace with your PostgreSQL password
        host="localhost"
    )
    return conn

# Home route (login page)
@app.route('/')
def index():
    if 'user_id' in session:
        return f"Welcome, {session['username']}!"
    return render_template('login.html')

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, username, password_hash, role FROM users WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and bcrypt.checkpw(password, user[2].encode('utf-8')):
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[3]
            return redirect(url_for('index'))
        else:
            return "Invalid credentials, try again."

    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('role', None)
    return redirect(url_for('index'))

# Register route (for testing purposes)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        role = request.form['role']

        # Hash the password
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password, salt).decode('utf-8')

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            (username, password_hash, role)
        )
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('login'))

    return render_template('register.html')

if __name__ == '__main__':
    app.run(debug=True)