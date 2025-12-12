#   Copyright 2025 Paweł Zuzelski <pawelz@execve.ch>
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

import polyline
import json
from shapely.geometry import LineString, MultiLineString
from shapely.ops import unary_union
import pandas as pd
import argparse
from datetime import datetime
import os

parser = argparse.ArgumentParser(description="Generates a map of new tracks taken since a specific date.")
parser.add_argument('--input_file', required=True, help="Path to the input CSV file.")
parser.add_argument('--since_day', required=True, help="The date to consider new tracks from (YYYY-MM-DD).")
parser.add_argument('--output_file', default='new_tracks.csv', help="Path to the output CSV file (default: new_tracks.csv).")
parser.add_argument('--trip_types', default='train', help="A comma-separated list of trip types to include (default: train).")
args = parser.parse_args()

# Check if output file exists to avoid overwriting
if os.path.exists(args.output_file):
    print(f"Error: Output file '{args.output_file}' already exists. Please remove it or specify a different file.")
    exit()

try:
    df = pd.read_csv(args.input_file)
except FileNotFoundError:
    print(f"Error: Input file not found at '{args.input_file}'")
    exit()

print(f"Total records loaded: {len(df)}")

# Process trip_types argument
trip_types_list = (item.strip() for item in args.trip_types.split(','))

# Filter for specified trip types
df_filtered = df[df['type'].isin(trip_types_list)].copy()

# Delete the original DataFrame to save memory
del df

# --- 2. Date Processing and Splitting ---

# Convert 'start_datetime' to datetime objects
df_filtered['start_datetime'] = pd.to_datetime(df_filtered['start_datetime'], errors='coerce')

# Drop records where the date could not be parsed
df_filtered = df_filtered.dropna(subset=['start_datetime']).copy()
print(f"Records remaining after dropping invalid dates: {len(df_filtered)}")

# Define the date boundary for splitting the data
since_date = pd.to_datetime(args.since_day)

# Split the dataset
# History: Records before the 'since_day'
df_history = df_filtered[df_filtered['start_datetime'] < since_date].copy()

# New: Records on or after the 'since_day'
df_new = df_filtered[df_filtered['start_datetime'] >= since_date].copy()

# Display results
print("\n--- Dataset Split Summary ---")
print(f"Total trips in filtered dataset: {len(df_filtered)}")
print(f"Historical trips (before {args.since_day}): {len(df_history)}")
print(f"New trips (on or after {args.since_day}): {len(df_new)}")

del df_filtered

# Add a 'year' column for the historical range summary
df_history_for_summary = df_history.copy()
df_history_for_summary['year'] = df_history_for_summary['start_datetime'].dt.year
min_year = df_history_for_summary['year'].min()
max_year = df_history_for_summary['year'].max()
print(f"Historical Year Range: {int(min_year)} to {int(max_year)}")
del df_history_for_summary

# --- 3. Path Decoding and Geometry Conversion ---
def parse_path_and_to_geometry(path_str):
    """Decodes the path string (Polyline or JSON) into a Shapely LineString."""
    if not isinstance(path_str, str) or len(path_str) < 2:
        return None

    coords = []

    # 1. Try Encoded Polyline format first (most common)
    try:
        # polyline.decode returns (lat, lon)
        latlon = polyline.decode(path_str)
        # Convert to [lon, lat] for consistency with GeoJSON/Shapely
        coords = [[p[1], p[0]] for p in latlon]
    except Exception:
        # 2. Try JSON format: [[lon, lat], [lon, lat], ...]
        if path_str.strip().startswith('['):
            try:
                coords = json.loads(path_str)
            except json.JSONDecodeError:
                pass

    if len(coords) < 2:
        return None

    return LineString(coords)


# --- Step 1: Convert paths to Shapely LineString objects ---
print("Converting paths to geometry...")

# Apply the conversion function to both DataFrames
df_new['geometry'] = df_new['path'].apply(parse_path_and_to_geometry)
df_history['geometry'] = df_history['path'].apply(parse_path_and_to_geometry)

# Remove failed conversions
df_new = df_new.dropna(subset=['geometry']).copy()
df_history = df_history.dropna(subset=['geometry']).copy()

geo_history = df_history['geometry'].tolist()

print(f"Valid new lines: {len(df_new)}")
print(f"Valid Historical lines: {len(geo_history)}")

# --- 4. Calculate Geometric Difference ---
# Instead of creating one large historical buffer, we will iterate through
print("Calculating difference: New lines NOT in History (iterative, memory-optimized approach)...")

new_segments_with_metadata = []

if not geo_history:
    # If there's no history, all new routes are "new"
    for index, new_trip_row in df_new.iterrows():
        new_segments_with_metadata.append({'geometry': new_trip_row['geometry'], 'original_trip': new_trip_row})
    print("No historical data found. All new routes are considered new.")
else:
    total_new_trips = len(df_new)
    for i, (index, new_trip_row) in enumerate(df_new.iterrows()):
        print(f"  Processing new trip {i + 1}/{total_new_trips}...", end='\r')
        new_line_geom = new_trip_row['geometry']
        current_new_part = new_line_geom
        for hist_line in geo_history:
            if current_new_part.is_empty:  # Optimization: if nothing left, break early
                break
            # Buffer the single historical line
            hist_line_buffer = hist_line.buffer(0.0015)
            # Subtract this single buffered historical line from the current_new_part
            current_new_part = current_new_part.difference(hist_line_buffer)

        if not current_new_part.is_empty:
            # Handle MultiLineString or GeometryCollection results from difference
            if current_new_part.geom_type in ['LineString', 'MultiLineString']:
                new_segments_with_metadata.append({'geometry': current_new_part, 'original_trip': new_trip_row})
            elif current_new_part.geom_type == 'GeometryCollection':
                for geom in current_new_part.geoms:
                    if geom.geom_type in ['LineString', 'MultiLineString']:
                        new_segments_with_metadata.append({'geometry': geom, 'original_trip': new_trip_row})
    print("\nDifference calculation complete.                ")

# --- 5. Finalize and Flatten Results ---
final_new_routes_with_metadata = []
for item in new_segments_with_metadata:
    geom = item['geometry']
    original_trip = item['original_trip']
    if geom.geom_type == 'LineString':
        final_new_routes_with_metadata.append({'geometry': geom, 'original_trip': original_trip})
    elif geom.geom_type == 'MultiLineString':
        # Flatten MultiLineString into individual LineStrings, each associated with the original trip
        for line in geom.geoms:
            final_new_routes_with_metadata.append({'geometry': line, 'original_trip': original_trip})

new_routes_geometries = [item['geometry'] for item in final_new_routes_with_metadata]
print(f"Found {len(new_routes_geometries)} new unique route fragments.")

# This variable holds the final list of new LineString geometries
# ready for plotting or further analysis.
print("Resulting geometries stored in the 'new_routes_geometries' variable.")

# --- 6. Prepare and Export New Routes to CSV ---
# Function to encode LineString to polyline
def encode_linestring_to_polyline(linestring):
    if linestring.geom_type != 'LineString':
        return None
    # polyline.encode expects (latitude, longitude) pairs
    coords_lat_lon = [(lat, lon) for lon, lat in linestring.coords]
    return polyline.encode(coords_lat_lon)

# Get original column names from the input file
original_columns = pd.read_csv(args.input_file, nrows=0).columns.tolist()

new_routes_data = []

print(f"Processing {len(final_new_routes_with_metadata)} new route geometries...")

for item in final_new_routes_with_metadata:
    encoded_path = encode_linestring_to_polyline(item['geometry'])
    if encoded_path:
        # Create a dictionary from the original trip's data
        new_route_dict = item['original_trip'].to_dict()
        # Overwrite the path with the new segment's polyline
        new_route_dict['path'] = encoded_path
        new_routes_data.append(new_route_dict)

df_new_routes = pd.DataFrame(new_routes_data)
df_new_routes = df_new_routes[original_columns]  # Ensure original column order

df_new_routes.to_csv(args.output_file, index=False)