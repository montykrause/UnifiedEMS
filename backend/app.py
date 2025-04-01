from flask import Flask, request, render_template, redirect, url_for, session
import psycopg2
import bcrypt
import googlemaps
import logging
from datetime import datetime

app = Flask(__name__)
app.secret_key = '11928240@mK'  # Your secret key

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize Google Maps client with your API key
gmaps = googlemaps.Client(key='AIzaSyB_pdbwazUTlMfotpQ6pHuvh_kyeyMfnmg')

# Database connection function
def get_db_connection():
    conn = psycopg2.connect(
        dbname="unifiedems",
        user="postgres",
        password="11928240@mK",  # Your PostgreSQL password
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

# Update location route for crew members
@app.route('/update_location', methods=['POST'])
def update_location():
    if 'user_id' not in session or session['role'] != 'crew':
        return redirect(url_for('index'))
    
    latitude = request.form.get('latitude')
    longitude = request.form.get('longitude')
    
    try:
        lat = float(latitude)
        lon = float(longitude)
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError("Invalid coordinates")
    except ValueError:
        logger.warning("Invalid location data submitted: lat=%s, lon=%s", latitude, longitude)
        return "Invalid location data", 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Assuming ambulance_locations has columns: crew_id, latitude, longitude, last_updated
        cur.execute(
            "INSERT INTO ambulance_locations (crew_id, latitude, longitude, last_updated) "
            "VALUES (%s, %s, %s, CURRENT_TIMESTAMP) "
            "ON CONFLICT (crew_id) DO UPDATE SET latitude = %s, longitude = %s, last_updated = CURRENT_TIMESTAMP",
            (session['user_id'], lat, lon, lat, lon)
        )
        conn.commit()
        logger.debug("Updated location for crew %s: lat=%s, lon=%s", session['user_id'], lat, lon)
    except psycopg2.Error as e:
        logger.error("Error updating location: %s", e)
        conn.rollback()
        return "Error updating location", 500
    finally:
        cur.close()
        conn.close()
    
    return redirect(url_for('crew_dashboard'))

# Initialize the Google Maps client with your API key
gmaps = googlemaps.Client(key='AIzaSyB_pdbwazUTlMfotpQ6pHuvh_kyeyMfnmg')

def find_closest_unit(hospital_lat, hospital_lon):
    """
    Find the closest unit to the hospital based on driving time.
    
    Args:
        hospital_lat (float): Latitude of the hospital.
        hospital_lon (float): Longitude of the hospital.
    
    Returns:
        int or None: The crew_id of the closest unit, or None if no units are available.
    """
    # Connect to your database (replace with your connection logic)
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Fetch available units with recent location updates
    cur.execute("""
        SELECT crew_id, latitude, longitude
        FROM ambulance_locations
        WHERE last_updated > NOW() - INTERVAL '1 hour'
    """)
    units = cur.fetchall()
    
    if not units:
        cur.close()
        conn.close()
        return None
    
    # Prepare origins (unit locations) and destination (hospital)
    origins = [(unit[1], unit[2]) for unit in units]  # List of (lat, lon) tuples
    destination = (hospital_lat, hospital_lon)
    
    # Call the Distance Matrix API
    result = gmaps.distance_matrix(
        origins=origins,
        destinations=[destination],
        mode="driving",  # Use driving directions
        units="metric",
        departure_time=datetime.now()  # Include traffic conditions
    )
    
    # Find the unit with the shortest driving time
    min_duration = float('inf')
    closest_unit_id = None
    
    for i, row in enumerate(result['rows']):
        element = row['elements'][0]
        if element['status'] == 'OK':
            duration = element['duration']['value']  # Time in seconds
            if duration < min_duration:
                min_duration = duration
                closest_unit_id = units[i][0]
    
    cur.close()
    conn.close()
    return closest_unit_id

# Example usage
hospital_lat, hospital_lon = 40.7128, -74.0060  # Example: New York City
closest_unit = find_closest_unit(hospital_lat, hospital_lon)
if closest_unit:
    print(f"Closest unit ID: {closest_unit}")
else:
    print("No available units.")




# Function to calculate distance and assign the closest crew
def assign_closest_crew(pickup_location):
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Fetch available crews with recent location updates (within the last hour)
        cur.execute(
            "SELECT al.crew_id, al.latitude, al.longitude "
            "FROM ambulance_locations al "
            "JOIN users u ON al.crew_id = u.user_id "
            "WHERE u.role = 'crew' AND al.last_updated > NOW() - INTERVAL '1 hour'"
        )
        crews = cur.fetchall()
        
        if not crews:
            logger.warning("No available crews found")
            return None
        
        # Assuming pickup_location is "lat,lng" (e.g., "40.7128,-74.0060")
        try:
            pickup_lat, pickup_lng = map(float, pickup_location.split(','))
        except ValueError:
            logger.error("Invalid pickup location format: %s", pickup_location)
            return None
        
        # Calculate distances using Google Maps Distance Matrix API
        origins = [(crew[1], crew[2]) for crew in crews]  # List of (lat, lng) for each crew
        destinations = [(pickup_lat, pickup_lng)]
        
        distance_matrix = gmaps.distance_matrix(
            origins=origins,
            destinations=destinations,
            mode="driving",
            units="metric"
        )
        
        min_distance = float('inf')
        closest_crew_id = None
        
        for i, row in enumerate(distance_matrix['rows']):
            elements = row['elements']
            if elements[0]['status'] == 'OK':
                distance = elements[0]['distance']['value']  # Distance in meters
                if distance < min_distance:
                    crew_id = crews[i][0]
                    # Check crew workload: max 3 active requests
                    cur.execute(
                        "SELECT COUNT(*) FROM transport_requests "
                        "WHERE assigned_crew_id = %s AND status != 'Completed'",
                        (crew_id,)
                    )
                    active_requests = cur.fetchone()[0]
                    if active_requests < 3:
                        min_distance = distance
                        closest_crew_id = crew_id
            else:
                logger.warning("Distance matrix error for crew %s: %s", crews[i][0], elements[0]['status'])
        
        if closest_crew_id:
            logger.debug("Assigned crew %s with distance %s meters", closest_crew_id, min_distance)
        else:
            logger.warning("No suitable crew found")
        
        return closest_crew_id
    except Exception as e:
        logger.error("Error in assign_closest_crew: %s", e)
        return None
    finally:
        cur.close()
        conn.close()

# Crew dashboard with status update functionality
@app.route('/crew', methods=['GET', 'POST'])
def crew_dashboard():
    if 'user_id' not in session or session['role'] != 'crew':
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    if request.method == 'POST':
        request_id = request.form['request_id']
        new_status = request.form['status']
        
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
    
    # Fetch active assignments
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

# Hospital dashboard with automatic assignment
@app.route('/hospital', methods=['GET', 'POST'])
def hospital_dashboard():
    if 'user_id' not in session or session['role'] != 'hospital_staff':
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        logger.debug("Received POST request for transport request: %s", request.form)
        pickup_location = request.form['pickup_location']  # e.g., "40.7128,-74.0060"
        destination = request.form['destination']
        patient_condition = request.form['patient_condition']
        
        # Automatically assign the closest crew
        assigned_crew_id = assign_closest_crew(pickup_location)
        if not assigned_crew_id:
            return "No available crews at this time.", 503
        
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO transport_requests (hospital_staff_id, pickup_location, destination, patient_condition, assigned_crew_id, status) "
                "VALUES (%s, %s, %s, %s, %s, 'Assigned') RETURNING request_id",
                (session['user_id'], pickup_location, destination, patient_condition, assigned_crew_id)
            )
            request_id = cur.fetchone()[0]
            conn.commit()
            logger.debug("Inserted transport request %s with assigned crew %s", request_id, assigned_crew_id)
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

# Supervisor dashboard with assignment functionality
@app.route('/supervisor', methods=['GET', 'POST'])
def supervisor_dashboard():
    if 'user_id' not in session or session['role'] != 'supervisor':
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            request_id = request.form['request_id']
            new_crew_id = request.form['new_crew_id']  # Updated form field name for clarity
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
        finally:
            cur.close()
            conn.close()
        return redirect(url_for('supervisor_dashboard'))
    
    # For GET requests
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Fetch all active requests, including unassigned ones
        cur.execute(
            "SELECT tr.request_id, tr.pickup_location, tr.destination, tr.patient_condition, tr.status, tr.assigned_crew_id, u.username "
            "FROM transport_requests tr "
            "LEFT JOIN users u ON tr.assigned_crew_id = u.user_id "
            "WHERE tr.status != 'Completed'"
        )
        requests = cur.fetchall()
        logger.debug("Fetched %d active requests for supervisor", len(requests))
        
        # Fetch all crews for assignment options
        cur.execute("SELECT user_id, username FROM users WHERE role = 'crew'")
        crews = cur.fetchall()
        logger.debug("Fetched %d available crews for assignment", len(crews))
        
        return render_template('supervisor_dashboard.html', username=session['username'], requests=requests, crews=crews)
    except psycopg2.Error as e:
        logger.error("Database error in supervisor dashboard: %s", e)
        return "Database error", 500
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    app.run(debug=True)