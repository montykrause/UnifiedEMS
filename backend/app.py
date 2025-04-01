from flask import Flask, request, render_template, redirect, url_for, session
import psycopg2
import bcrypt
import googlemaps
import logging
from datetime import datetime

app = Flask(__name__)
app.secret_key = '11928240@mK'  # Replace with a secure secret key in production

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Google Maps client
gmaps = googlemaps.Client(key='AIzaSyB_pdbwazUTlMfotpQ6pHuvh_kyeyMfnmg')

# Database connection function
def get_db_connection():
    conn = psycopg2.connect(
        dbname="unifiedems",
        user="postgres",
        password="11928240@mK",  # Replace with your actual PostgreSQL password
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

# Register route with hospital ID validation and hospital list
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        role = request.form['role']
        hospital_id = request.form.get('hospital_id')  # Optional field

        # Hash the password
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password, salt).decode('utf-8')

        conn = get_db_connection()
        cur = conn.cursor()

        try:
            # If the user is hospital staff, validate hospital_id
            if role == 'hospital_staff':
                if not hospital_id:
                    return "Hospital ID is required for hospital staff", 400
                try:
                    hospital_id = int(hospital_id)
                except ValueError:
                    return "Invalid Hospital ID", 400
                cur.execute("SELECT hospital_id FROM hospitals WHERE hospital_id = %s", (hospital_id,))
                if not cur.fetchone():
                    return "Invalid Hospital ID", 400

            # Insert the user into the users table
            cur.execute(
                "INSERT INTO users (username, password_hash, role, hospital_id) "
                "VALUES (%s, %s, %s, %s)",
                (username, password_hash, role, hospital_id if hospital_id else None)
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
    else:
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT hospital_id, name FROM hospitals")
            hospitals = cur.fetchall()
        except psycopg2.Error as e:
            logger.error("Error fetching hospitals: %s", e)
            hospitals = []
        finally:
            cur.close()
            conn.close()
        return render_template('register.html', hospitals=hospitals)

# Update location route for crew members
@app.route('/update_location', methods=['POST'])
def update_location():
    if 'user_id' not in session or session['role'] != 'crew':
        return redirect(url_for('index'))
    
    try:
        latitude = float(request.form['latitude'])
        longitude = float(request.form['longitude'])
    except ValueError:
        return "Invalid latitude or longitude", 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO ambulance_locations (crew_id, latitude, longitude, last_updated) "
            "VALUES (%s, %s, %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT (crew_id) DO UPDATE SET latitude = %s, longitude = %s, last_updated = CURRENT_TIMESTAMP",
            (session['user_id'], latitude, longitude, latitude, longitude)
        )
        conn.commit()
        logger.debug("Updated location for crew %s: lat=%s, lon=%s", session['user_id'], latitude, longitude)
    except psycopg2.Error as e:
        logger.error("Error updating location: %s", e)
        conn.rollback()
        return "Error updating location", 500
    finally:
        cur.close()
        conn.close()
    return redirect(url_for('crew_dashboard'))

# Function to find the closest unit based on driving time
def find_closest_unit(hospital_lat, hospital_lon):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Fetch available units with recent location updates
        cur.execute("""
            SELECT crew_id, latitude, longitude
            FROM ambulance_locations
            WHERE last_updated > NOW() - INTERVAL '1 hour'
        """)
        units = cur.fetchall()
        
        if not units:
            logger.warning("No available units found")
            return None
        
        # Prepare origins (unit locations) and destination (hospital)
        origins = [(unit[1], unit[2]) for unit in units]
        destination = (hospital_lat, hospital_lon)
        
        # Call the Distance Matrix API
        result = gmaps.distance_matrix(
            origins=origins,
            destinations=[destination],
            mode="driving",
            units="metric",
            departure_time=datetime.now()  # Include traffic conditions
        )
        
        min_duration = float('inf')
        closest_unit_id = None
        
        for i, row in enumerate(result['rows']):
            element = row['elements'][0]
            if element['status'] == 'OK':
                duration = element['duration']['value']  # Time in seconds
                if duration < min_duration:
                    # Check crew workload: max 3 active requests
                    cur.execute(
                        "SELECT COUNT(*) FROM transport_requests "
                        "WHERE assigned_crew_id = %s AND status != 'Completed'",
                        (units[i][0],)
                    )
                    active_requests = cur.fetchone()[0]
                    if active_requests < 3:
                        min_duration = duration
                        closest_unit_id = units[i][0]
            else:
                logger.warning("Distance matrix error for unit %s: %s", units[i][0], element['status'])
        
        if closest_unit_id:
            logger.debug("Assigned unit %s with driving time %s seconds", closest_unit_id, min_duration)
        else:
            logger.warning("No suitable unit found")
        return closest_unit_id
    except Exception as e:
        logger.error("Error in find_closest_unit: %s", e)
        return None
    finally:
        cur.close()
        conn.close()

# Crew dashboard with status update functionality
@app.route('/crew', methods=['GET', 'POST'])
def crew_dashboard():
    # Authentication
    if 'user_id' not in session or session['role'] != 'crew':
        return redirect(url_for('index'))
    
    # Database connection
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Handle POST request for status update
    if request.method == 'POST':
        request_id = request.form['request_id']
        new_status = request.form['status']
        # Update status in the database
        try:
            cur.execute(
                "UPDATE transport_requests SET status = %s, last_updated = CURRENT_TIMESTAMP "
                "WHERE request_id = %s AND assigned_crew_id = %s",
                (new_status, request_id, session['user_id'])
            )
            conn.commit()
            logger.debug("Updated status of request %s to %s by crew %s", request_id, new_status, session['user_id'])
        except psycopg2.Error as e:
            logger.error("Error updating request status: %s", e)
            conn.rollback()
            return "Error updating status", 500
    
    # Fetch assignments and location for GET request or after POST
    try:
        cur.execute(
            "SELECT request_id, pickup_location, destination, patient_condition, status "
            "FROM transport_requests WHERE assigned_crew_id = %s AND status != 'Completed'",
            (session['user_id'],)
        )
        assignments = cur.fetchall()
        logger.debug("Fetched %d assignments for crew user_id %s", len(assignments), session['user_id'])
        
        cur.execute(
            "SELECT latitude, longitude, last_updated FROM ambulance_locations WHERE crew_id = %s",
            (session['user_id'],)
        )
        location = cur.fetchone()
        if location:
            current_latitude, current_longitude, last_updated = location
        else:
            current_latitude, current_longitude, last_updated = None, None, None
    except psycopg2.Error as e:
        logger.error("Error fetching assignments or location: %s", e)
        assignments = []
        current_latitude, current_longitude, last_updated = None, None, None
    finally:
        cur.close()
        conn.close()
    
    # Render the template
    return render_template('crew_dashboard.html', username=session['username'], assignments=assignments,
                           current_latitude=current_latitude, current_longitude=current_longitude, last_updated=last_updated)

# Hospital dashboard with automatic assignment
@app.route('/hospital', methods=['GET', 'POST'])
def hospital_dashboard():
    if 'user_id' not in session or session['role'] != 'hospital_staff':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Fetch hospital coordinates based on user's hospital_id
        cur.execute("""
            SELECT h.latitude, h.longitude
            FROM hospitals h
            JOIN users u ON h.hospital_id = u.hospital_id
            WHERE u.user_id = %s
        """, (session['user_id'],))
        hospital_coords = cur.fetchone()
        if not hospital_coords:
            logger.error("No hospital found for user_id %s", session['user_id'])
            return "Hospital not configured", 500
        hospital_lat, hospital_lon = hospital_coords
        
        if request.method == 'POST':
            pickup_location = request.form['pickup_location']
            destination = request.form['destination']
            patient_condition = request.form['patient_condition']
            
            # Find the closest unit
            assigned_crew_id = find_closest_unit(hospital_lat, hospital_lon)
            if not assigned_crew_id:
                return "No available crews at this time.", 503
            
            # Insert the transport request
            cur.execute("""
                INSERT INTO transport_requests (
                    hospital_staff_id, pickup_location, pickup_latitude, pickup_longitude,
                    destination, patient_condition, assigned_crew_id, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'Assigned')
                RETURNING request_id
            """, (session['user_id'], pickup_location, hospital_lat, hospital_lon, destination, patient_condition, assigned_crew_id))
            request_id = cur.fetchone()[0]
            conn.commit()
            logger.debug("Inserted transport request %s with assigned crew %s", request_id, assigned_crew_id)
            return redirect(url_for('hospital_dashboard'))
        
        # Fetch user's transport requests for GET request
        cur.execute(
            "SELECT request_id, pickup_location, destination, patient_condition, status "
            "FROM transport_requests WHERE hospital_staff_id = %s ORDER BY request_time DESC",
            (session['user_id'],)
        )
        requests = cur.fetchall()
        logger.debug("Fetched %d requests for hospital staff user_id %s", len(requests), session['user_id'])
        return render_template('hospital_dashboard.html', username=session['username'], requests=requests)
    except psycopg2.Error as e:
        logger.error("Database error in hospital dashboard: %s", e)
        return "Error: " + str(e), 500
    finally:
        cur.close()
        conn.close()

# Supervisor dashboard with assignment functionality
@app.route('/supervisor', methods=['GET', 'POST'])
def supervisor_dashboard():
    if 'user_id' not in session or session['role'] != 'supervisor':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            request_id = request.form['request_id']
            new_crew_id = request.form['new_crew_id']
            cur.execute(
                "UPDATE transport_requests SET assigned_crew_id = %s, last_updated = CURRENT_TIMESTAMP "
                "WHERE request_id = %s",
                (new_crew_id, request_id)
            )
            conn.commit()
            logger.debug("Reassigned request %s to crew %s", request_id, new_crew_id)
        except psycopg2.Error as e:
            logger.error("Error reassigning request: %s", e)
            conn.rollback()
            return "Error reassigning request", 500
        finally:
            cur.close()
            conn.close()
        return redirect(url_for('supervisor_dashboard'))
    
    try:
        cur.execute(
            "SELECT tr.request_id, tr.pickup_location, tr.destination, tr.patient_condition, tr.status, tr.assigned_crew_id, u.username "
            "FROM transport_requests tr "
            "LEFT JOIN users u ON tr.assigned_crew_id = u.user_id "
            "WHERE tr.status != 'Completed'"
        )
        requests = cur.fetchall()
        cur.execute("SELECT user_id, username FROM users WHERE role = 'crew'")
        crews = cur.fetchall()
        logger.debug("Fetched %d active requests and %d crews for supervisor", len(requests), len(crews))
        return render_template('supervisor_dashboard.html', username=session['username'], requests=requests, crews=crews)
    except psycopg2.Error as e:
        logger.error("Database error in supervisor dashboard: %s", e)
        return "Database error", 500
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)