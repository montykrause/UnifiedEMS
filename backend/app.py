from flask import Flask, request, render_template, redirect, url_for, session
import psycopg2
import bcrypt
import logging

app = Flask(__name__)
app.secret_key = '11928240@mK'  # Replace with a strong, random key

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Database connection function
def get_db_connection():
    conn = psycopg2.connect(
        dbname="unifiedems",
        user="postgres",
        password="11928240@mK",  # Replace with your PostgreSQL password
        host="localhost"
    )
    return conn

# Home route (login page or redirect to dashboard)
@app.route('/')
def index():
    if 'user_id' in session:
        if session['role'] == 'crew':
            return redirect(url_for('crew_dashboard'))
        elif session['role'] == 'hospital_staff':
            return redirect(url_for('hospital_dashboard'))
        elif session['role'] == 'supervisor':
            return redirect(url_for('supervisor_dashboard'))
    return render_template('login.html')

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')

        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id, username, password_hash, role FROM users WHERE username = %s", (username,))
            user = cur.fetchone()
            if user and bcrypt.checkpw(password, user[2].encode('utf-8')):
                session['user_id'] = user[0]
                session['username'] = user[1]
                session['role'] = user[3]
                logger.debug("User %s logged in successfully with role %s", username, user[3])
                return redirect(url_for('index'))
            else:
                logger.warning("Failed login attempt for username: %s", username)
                return "Invalid credentials, try again."
        except psycopg2.Error as e:
            logger.error("Database error during login: %s", e)
            return "Error accessing database", 500
        finally:
            cur.close()
            conn.close()

    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('role', None)
    logger.debug("User logged out")
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
        try:
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username, password_hash, role)
            )
            conn.commit()
            logger.debug("User %s registered successfully with role %s", username, role)
            return redirect(url_for('login'))
        except psycopg2.Error as e:
            logger.error("Error registering user %s: %s", username, e)
            conn.rollback()
            return "Error registering user", 500
        finally:
            cur.close()
            conn.close()

    return render_template('register.html')

# Crew dashboard (shows assignments)
@app.route('/crew')
def crew_dashboard():
    if 'user_id' not in session or session['role'] != 'crew':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT request_id, pickup_location, destination, patient_condition, status "
            "FROM transport_requests WHERE assigned_crew_id = %s AND status != 'Completed'",
            (session['user_id'],)
        )
        assignments = cur.fetchall()
        logger.debug("Fetched %d assignments for crew user_id %s", len(assignments), session['user_id'])
    except psycopg2.Error as e:
        logger.error("Error fetching assignments: %s", e)
        assignments = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('crew_dashboard.html', username=session['username'], assignments=assignments)

# Hospital staff dashboard (submit and view transport requests)
@app.route('/hospital', methods=['GET', 'POST'])
def hospital_dashboard():
    if 'user_id' not in session or session['role'] != 'hospital_staff':
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        logger.debug("Received POST request for transport request: %s", request.form)
        pickup_location = request.form['pickup_location']
        destination = request.form['destination']
        patient_condition = request.form['patient_condition']
        
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO transport_requests (hospital_staff_id, pickup_location, destination, patient_condition) "
                "VALUES (%s, %s, %s, %s) RETURNING request_id",
                (session['user_id'], pickup_location, destination, patient_condition)
            )
            request_id = cur.fetchone()[0]
            conn.commit()
            logger.debug("Inserted transport request with ID: %s", request_id)
        except psycopg2.Error as e:
            logger.error("Error inserting transport request: %s", e)
            conn.rollback()
            return "Error submitting request", 500
        finally:
            cur.close()
            conn.close()
        return redirect(url_for('hospital_dashboard'))
    
    # For GET requests, fetch the user's transport requests
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT request_id, pickup_location, destination, patient_condition, status "
            "FROM transport_requests WHERE hospital_staff_id = %s ORDER BY request_time DESC",
            (session['user_id'],)
        )
        requests = cur.fetchall()
        logger.debug("Fetched %d requests for hospital staff user_id %s", len(requests), session['user_id'])
    except psycopg2.Error as e:
        logger.error("Error fetching requests: %s", e)
        requests = []
    finally:
        cur.close()
        conn.close()
    return render_template('hospital_dashboard.html', username=session['username'], requests=requests)

# Supervisor dashboard (view all requests)
@app.route('/supervisor')
def supervisor_dashboard():
    if 'user_id' not in session or session['role'] != 'supervisor':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT request_id, pickup_location, destination, patient_condition, status, assigned_crew_id "
            "FROM transport_requests ORDER BY request_time DESC"
        )
        requests = cur.fetchall()
        logger.debug("Fetched %d requests for supervisor", len(requests))
    except psycopg2.Error as e:
        logger.error("Error fetching requests: %s", e)
        requests = []
    finally:
        cur.close()
        conn.close()
    
    return render_template('supervisor_dashboard.html', username=session['username'], requests=requests)

if __name__ == '__main__':
    app.run(debug=True)