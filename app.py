# Import necessary libraries
from flask import Flask, request, render_template, Response
import sqlite3
import traceback
import re
import csv
from io import StringIO
import json
import os
from datetime import datetime
from dateutil import parser

# Initialize Flask app
app = Flask(__name__)
# Regular expression pattern for valid BBUSerials
pattern =  r'^(?=.*[a-zA-Z])(?=.*[0-9])[a-zA-Z0-9]{13}$'

# Function to establish a connection to the database
def get_db():
    conn = sqlite3.connect('BBU_Rack_test.db')
    return conn, conn.cursor()

# Function to create the table schema if it doesn't exist
def create_table():
    conn, cursor = get_db()
    cursor.execute('''CREATE TABLE IF NOT EXISTS serial_numbers
                      (ID INTEGER PRIMARY KEY AUTOINCREMENT, 
                       BBUSerial TEXT, 
                       TotalCount INTEGER, 
                       FirstUsedDate TIMESTAMP, 
                       LastUsedDate TIMESTAMP)''')
    conn.close()


def validate_serial(serial):
    return re.match(pattern, serial)

# Home page route
@app.route('/')
def home():
    return render_template('index.html')

# Handle serial number submission route
@app.route('/submit', methods=['POST'])
def submit():
    conn, cursor = get_db()

    # Get submitted serial number and current timestamp
    serial_number = request.form['serial_number'].replace(" ", "")
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Validate serial number length
    # Validate serial number length and pattern
    if len(serial_number) != 13 or not validate_serial(serial_number):
        conn.close()
        #return render_template('index.html', error='Invalid serial number!')
        render_template('index.html', error='Invalid serial number!', focus_cursor=request.args.get('focus_cursor'))


    try:
        # Insert or ignore the serial number, update total count and last used date
        cursor.execute("INSERT OR IGNORE INTO serial_numbers (BBUSerial, TotalCount, FirstUsedDate, LastUsedDate) VALUES (?, 0, ?, ?)", (serial_number, current_time, current_time))
        cursor.execute("UPDATE serial_numbers SET TotalCount = TotalCount + 1, LastUsedDate = ? WHERE BBUSerial = ?", (current_time, serial_number))
        conn.commit()
        conn.close()
        # return render_template('index.html', success='Serial number recorded successfully!')
        return render_template('index.html', success='Serial number recorded successfully!', focus_cursor=request.args.get('focus_cursor'))

    except Exception as e:
        conn.close()
        return render_template('index.html', error=f'Error recording serial number: {str(e)}', focus_cursor=request.args.get('focus_cursor'))

# Get count and last scanned time for a serial number or exceeding a given count threshold
@app.route('/count')
def count():
    conn, cursor = get_db()

    serial_number = request.args.get('serial_number')
    threshold = request.args.get('threshold')
    
    if serial_number:
        cursor.execute("SELECT TotalCount , LastUsedDate FROM serial_numbers WHERE BBUSerial = ?", (serial_number,))
        result = cursor.fetchone()

        conn.close()

        if result:
            count = result[0]
            last_scanned_time = result[1]
            return f"The serial number {serial_number} has been scanned {count} time(s). Last scanned time: {last_scanned_time}"
        else:
            return f"The serial number {serial_number} has not been scanned yet."
    elif threshold:
        cursor.execute("SELECT BBUSerial, scan_time FROM serial_numbers WHERE TotalCount > ?", (threshold,))
        results = cursor.fetchall()

        conn.close()

        if results:
            serial_numbers = [f"{row[0]} (Last scanned time: {row[1]})" for row in results]
            return f"The following serial numbers have been scanned more than {threshold} time(s): {', '.join(serial_numbers)}"
        else:
            return f"No serial numbers have been scanned more than {threshold} time(s)."
    else:
        conn.close()
        return "Invalid request."

# Clear the database route
@app.route('/clear_db')
def clear_db():
    return """
    <form method="post" action="/clear_confirm">
        <p>Are you sure you want to clear the database?</p>
        <input type="submit" value="Yes, clear the database">
    </form>
    """


# Clear confirmation route
@app.route('/clear_confirm', methods=['POST'])
def clear_confirm():
    if request.method == 'POST':
        try:
            conn, cursor = get_db()
            cursor.execute("DELETE FROM serial_numbers")
            conn.commit()
            conn.close()

            # Backup database with current date
            current_date = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
            if os.path.exists('BBU_Rack_test.db'):
                backup_db_name = f"backup_serial_numbers_{current_date}.db"
                os.rename('BBU_Rack_test.db', backup_db_name)

            # Backup JSON file with current date
            if os.path.exists('data.json'):
                backup_json_name = f"backup_data_{current_date}.json"
                os.rename('data.json', backup_json_name)

            return "Database cleared successfully!"
        except Exception as e:
            return f"Failed to clear database. Error: {str(e)}"
    else:
        return "Confirmation failed"

# Get all serial numbers scanned more than a specified count route
@app.route('/above_threshold')
def above_threshold():
    conn, cursor = get_db()

    threshold = request.args.get('threshold')

    if threshold:
        cursor.execute("SELECT BBUSerial, TotalCount, LastUsedDate FROM serial_numbers WHERE TotalCount > ?", (threshold,))
        results = cursor.fetchall()

        conn.close()

        if results:
            return render_template('above_threshold.html', serial_data=results, threshold_value=threshold)
        else:
            return f"No serial numbers have been scanned more than {threshold} time(s)."
    else:
        conn.close()
        return "Invalid request. Please provide a threshold."

# Display all scanned serial numbers with counts route
@app.route('/all_serial_numbers')
def all_serial_numbers():
    conn, cursor = get_db()

    try:
        cursor.execute("SELECT BBUSerial , TotalCount, LastUsedDate FROM serial_numbers")
        results = cursor.fetchall()

        conn.close()

        if not results:
            return render_template('all_serial_numbers.html', serial_data=[], empty_db=True)
        else:
            return render_template('all_serial_numbers.html', serial_data=results, empty_db=False)
    except sqlite3.OperationalError as e:
        conn.close()
        return render_template('all_serial_numbers.html', serial_data=[], empty_db=True)



# Function to import data from a JSON file into the database
def import_from_json(file_path):
    if not os.path.exists('BBU_Rack_test.db'):
        create_table()  # Create table if the database doesn't exist
    else:
        # Check if the table 'serial_numbers' exists in the database
        conn, cursor = get_db()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='serial_numbers'")
        table_exists = cursor.fetchone()
        conn.close()

        if not table_exists:
            create_table()  # Create table if it doesn't exist

    conn = sqlite3.connect('BBU_Rack_test.db')
    cursor = conn.cursor()

    try:
        with open(file_path, 'r') as file:
            data = json.load(file)
            for entry in data:
                serial_number = entry.get('BBUSerial', '')
                last_used_date = entry.get('LastUsedDate', '')  # Get 'LastUsedDate' or empty string if missing
                if len(serial_number) == 13 or validate_serial(serial_number):
                    cursor.execute("INSERT INTO serial_numbers (ID, BBUSerial, TotalCount, FirstUsedDate, LastUsedDate) VALUES (?, ?, ?, ?, ?)",
                        (entry.get('ID', ''), serial_number, entry.get('TotalCount', 0), entry.get('FirstUsedDate', ''), last_used_date))
            conn.commit()
            conn.close()
            return "Data imported successfully! Entries with 13-character serial numbers inserted."
    except Exception as e:
        print(f"Error: {str(e)}")
        traceback.print_exc()  # Print the traceback for detailed error information
        conn.close()
        return f"Failed to import data. Error: {str(e)}"
    
    
# Route to handle JSON import
@app.route('/import_json', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return "No file part"
        
        file = request.files['file']
        
        if file.filename == '':
            return "No selected file"
        
        if file and file.filename.endswith('.json'):
            file_path = 'temp.json'  # Temporarily rename the file
            file.save(file_path)  # Save the uploaded file

            # Call the import function passing the file path
            result = import_from_json(file_path)

            # Close and remove the file
            file.close()
            os.remove(file_path)

            return result
        else:
            return "Invalid file format. Please upload a JSON file."
    except Exception as e:
        return f"Failed to upload file. Error: {str(e)}"
    

# Define the route to handle importing from JSON file
@app.route('/import_json', methods=['POST'])
def import_json():
    file = request.files['file']
    if file.filename.endswith('.json'):
        file.save(file.filename)  # Save the uploaded file
        
        # Call the import function passing the file path
        result = import_from_json(file.filename)

        # Delete the temporary file
        os.remove(file.filename)

        return result
    else:
        return "Invalid file format. Please upload a JSON file."

# Export to CSV file route
@app.route('/export_csv')
def export_csv():
    conn, cursor = get_db()

    cursor.execute("SELECT BBUSerial , TotalCount, LastUsedDate FROM serial_numbers")
    results = cursor.fetchall()

    conn.close()

    # Prepare CSV data
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Serial Number', 'Scan Count', 'Last Used Date'])
    writer.writerows(results)

    # Create a Flask Response with CSV data
    response = Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=serialNumbers_History.csv"}
    )

    return response
@app.route('/export_above_threshold')

# Export to CSV file route only the ones that are above the threshold 
def export_above_threshold():
    threshold = request.args.get('threshold')
    conn, cursor = get_db()

    if threshold:
        cursor.execute("SELECT BBUSerial, TotalCount, LastUsedDate FROM serial_numbers WHERE TotalCount > ?", (threshold,))
        results = cursor.fetchall()

        conn.close()

        if results:
            # Prepare CSV data
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(['Serial Number', 'Scanned Count', 'Last Scanned Time'])
            writer.writerows(results)

            # Create a Flask Response with CSV data
            response = Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={"Content-Disposition": f"attachment;filename=above_threshold_{threshold}.csv"}
            )
            return response

    return "No data to export"

# Get all serial numbers scanned above and beyond the date 
@app.route('/filter_by_date', methods=['GET'])
def filter_by_date():
    filter_date = request.args.get('filter_date')
    conn, cursor = get_db()

    try:
        # Parse the filter_date using dateutil.parser
        #parsed_date = parser.parse(filter_date, dayfirst=True)
        

        # Format the parsed_date to match the database date format (YYYY-MM-DD)
        formatted_filter_date = datetime.strptime(filter_date, '%m/%d/%Y').strftime('%Y-%m-%d')

        conn, cursor = get_db()

        cursor.execute("SELECT BBUSerial, TotalCount, LastUsedDate FROM serial_numbers WHERE strftime('%Y-%m-%d', LastUsedDate) >= ?", (formatted_filter_date,))
        results = cursor.fetchall()

        conn.close()

        if results:
                return render_template('filtered_by_date.html', serial_data=results, filter_date=formatted_filter_date)
        else:
            return f"No data found for {formatted_filter_date}"
    except ValueError:
            return "Date format does not match. Please provide a date in the format YYYY-MM-DD."

    return "No date provided"
# Run the Flask app
if __name__ == '__main__':
    app.run(host='IEDUBM0APP01', port=5000)
