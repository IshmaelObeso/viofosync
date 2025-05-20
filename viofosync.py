#!/usr/bin/env python3

# Copyright (c) 2024 Rob Smith
# Based on BlackVueSync by Alessandro Colomba (https://github.com/acolomba)
# GPS extraction method by Sergei Franco
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
# Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

__version__ = "1.1"

import argparse
import datetime
from collections import namedtuple
import glob
import http.client
import logging
import re
import os
import time
import urllib
import urllib.parse
import urllib.request
import socket
import xml.etree.ElementTree as ET
import struct



# Logging setup
Recording = namedtuple("Recording", "filename filepath size timecode datetime attr")
logging.basicConfig(format="%(asctime)s: %(levelname)s %(message)s", level=logging.DEBUG)
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)  # Ensure logger is set to DEBUG level
logger = logging.getLogger()
cron_logger = logging.getLogger("cron")

# Group name globs, keyed by grouping
group_name_globs = {
    "none": None,
    "daily": "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]",
    "weekly": "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]",
    "monthly": "[0-9][0-9][0-9][0-9]-[0-9][0-9]",
    "yearly": "[0-9][0-9][0-9][0-9]",
}

# Downloaded recording filename glob pattern
downloaded_filename_glob = "[0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9][FR].MP4"

# Downloaded recording filename regular expression
downloaded_filename_re = re.compile(r"""^(?P<year>\d{4})_(?P<month>\d{2})(?P<day>\d{2})
    _(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})_(?P<sequence>\d{6})(?P<camera>[FR])\.MP4$""", re.VERBOSE)

def to_downloaded_recording(filename, grouping):
    """extracts destination recording information from a filename"""
    logger.debug(f"Attempting to match filename: {filename} with pattern: {downloaded_filename_re.pattern}")
    filename_match = re.match(downloaded_filename_re, filename)
    logger.debug(f"Filename match result: {filename_match}")

    if filename_match is None:
        logger.debug(f"No match found for filename: {filename}")
        return None

    year = int(filename_match.group("year"))
    month = int(filename_match.group("month"))
    day = int(filename_match.group("day"))
    hour = int(filename_match.group("hour"))
    minute = int(filename_match.group("minute"))
    second = int(filename_match.group("second"))
    logger.debug(f"Extracted date components - Year: {year}, Month: {month}, Day: {day}, Hour: {hour}, Minute: {minute}, Second: {second}")
    recording_datetime = datetime.datetime(year, month, day, hour, minute, second)
    logger.debug(f"Constructed datetime: {recording_datetime}")
    recording_group_name = get_group_name(recording_datetime, grouping)

    return Recording(filename, None, None, recording_datetime, None, None)
dry_run = False
max_disk_used_percent = 90
cutoff_date = None
socket_timeout = 10.0

# Modify the Recording namedtuple to match Viofo's file information
Recording = namedtuple("Recording", "filename filepath size timecode datetime attr")

# Update the filename regular expression to match Viofo's naming convention
filename_re = re.compile(r"""(?P<year>\d{4})_(?P<month>\d{2})(?P<day>\d{2})
    _(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})
    _(?P<sequence>\d{5})(?P<camera>[FR])\.MP4""", re.VERBOSE)

def parse_viofo_datetime(time_str):
    """Parse the datetime string from Viofo's format"""
    return datetime.datetime.strptime(time_str, "%Y/%m/%d %H:%M:%S")

def get_dashcam_filenames(base_url):
    """gets the recording filenames from the Viofo dashcam"""
    logger.debug(f"Attempting to get file list from {base_url}")
    try:
        url = f"{base_url}/?custom=1&cmd=3015&par=1"
        logger.debug(f"Sending request to URL: {url}")
        request = urllib.request.Request(url)
        response = urllib.request.urlopen(request, timeout=socket_timeout)

        response_status_code = response.getcode()
        logger.debug(f"Response status code: {response_status_code}")
        if response_status_code != 200:
            raise RuntimeError(f"Error response from : {base_url} ; status code : {response_status_code}")

        xml_data = response.read().decode('utf-8')
        logger.debug(f"Received XML data: {xml_data[:500]}...")  # Log first 500 characters of XML
        root = ET.fromstring(xml_data)
        
        recordings = []
        for file_elem in root.findall(".//File"):
            name = file_elem.find("NAME").text
            filepath = file_elem.find("FPATH").text
            size = int(file_elem.find("SIZE").text)
            timecode = int(file_elem.find("TIMECODE").text)
            time = parse_viofo_datetime(file_elem.find("TIME").text)
            attr = int(file_elem.find("ATTR").text)
            
            recording = Recording(name, filepath, size, timecode, time, attr)
            recordings.append(recording)
            logger.debug(f"Found recording: {recording}")
        
        logger.info(f"Total recordings found: {len(recordings)}")
        logger.info("Successfully retrieved file list from dashcam.")
        return recordings
    except urllib.error.URLError as e:
        logger.error(f"URLError when trying to get file list: {e}")
        raise RuntimeError(f"Cannot obtain list of recordings from dashcam at address : {base_url}; error : {e}")
    except socket.timeout as e:
        logger.error(f"Socket timeout when trying to get file list: {e}")
        raise UserWarning(f"Timeout communicating with dashcam at address : {base_url}; error : {e}")
    except http.client.RemoteDisconnected as e:
        logger.error(f"Remote disconnected when trying to get file list: {e}")
        raise UserWarning(f"Dashcam disconnected without a response; address : {base_url}; error : {e}")
    except ET.ParseError as e:
        logger.error(f"XML parsing error: {e}")
        logger.error(f"Problematic XML data: {xml_data}")
        raise RuntimeError(f"Error parsing XML response from dashcam: {e}")

def get_filepath(destination, group_name, filename):
    """constructs a path for a recording file from the destination, group name and filename (or glob pattern)"""
    if group_name:
        return os.path.join(destination, group_name, filename)
    else:
        return os.path.join(destination, filename)

def get_remote_size(url, timeout):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        size = resp.headers.get("Content-Length")
        return int(size) if size and size.isdigit() else None


def download_file(base_url, recording, destination, group_name, socket_timeout, dry_run):
    """downloads a file only once its size has stabilized via two HEAD checks"""
    logger.debug(f"Attempting to download file: {recording.filename}")
    # ensure destination directory exists
    if group_name:
        group_dir = os.path.join(destination, group_name)
        ensure_destination(group_dir)

    dest_path = (os.path.join(destination, group_name, recording.filename)
                 if group_name else os.path.join(destination, recording.filename))

    # Build URL for HEAD
    cleaned = recording.filepath.replace('A:', '').replace('\\', '/')
    url = f"{base_url}/{cleaned}"

    # Check size-stability
    try:
        first_size = get_remote_size(url, socket_timeout)
        time.sleep(10)
        second_size = get_remote_size(url, socket_timeout)
    except Exception as e:
        logger.warning(f"Unable to verify remote size for {recording.filename}: {e}")
        # proceed to download anyway
        first_size = second_size = None

    if first_size is not None and second_size is not None and first_size != second_size:
        logger.info(
            f"Remote file still changing: {recording.filename} ({first_size} -> {second_size}), retry later"
        )
        return False, None

    # Skip if already downloaded and size matches
    if os.path.exists(dest_path) and first_size is not None:
        local_size = os.path.getsize(dest_path)
        if local_size == first_size:
            logger.debug(
                f"Skipping download (up-to-date): {recording.filename} ({local_size} bytes)"
            )
            return False, None

    if dry_run:
        logger.debug(f"DRY RUN Would download file : {recording.filename}")
        return True, None

    try:
        logger.info(f"Starting download for file: {recording.filename}")
        start = time.perf_counter()
        urllib.request.urlretrieve(url, dest_path)
        elapsed = time.perf_counter() - start

        logger.info(
            f"Successfully downloaded {recording.filename} in {elapsed:.1f}s"
        )
        return True, None

    except urllib.error.URLError as e:
        logger.error(f"URLError downloading {recording.filename}: {e}")
        cron_logger.warning(f"Ignoring failed download: {recording.filename}")
        return False, None
    except socket.timeout as e:
        logger.error(f"Timeout downloading {recording.filename}: {e}")
        raise UserWarning(f"Timeout for {recording.filename}: {e}")
    except http.client.RemoteDisconnected as e:
        logger.error(f"Remote disconnected during download {recording.filename}: {e}")
        cron_logger.warning(f"Ignoring interrupted download: {recording.filename}")
        return False, None


def get_downloaded_recordings(destination, grouping):
    """reads files from the destination directory and returns them as a set of filenames with parsed dates"""
    group_name_glob = group_name_globs[grouping]

    downloaded_filepath_glob = get_filepath(destination, group_name_glob, downloaded_filename_glob)

    downloaded_filepaths = glob.glob(downloaded_filepath_glob)

    recordings = set()
    for filepath in downloaded_filepaths:
        filename = os.path.basename(filepath)
        filename_match = re.match(downloaded_filename_re, filename)
        if filename_match:
            year = int(filename_match.group("year"))
            month = int(filename_match.group("month"))
            day = int(filename_match.group("day"))
            recording_date = datetime.date(year, month, day)
            recordings.add((filename, recording_date))
    return recordings

def get_outdated_recordings(destination, grouping):
    """returns the recordings prior to the cutoff date"""
    if cutoff_date is None:
        return []

    downloaded_recordings = get_downloaded_recordings(destination, grouping)

    outdated_recordings = [filename for filename, recording_date in downloaded_recordings if recording_date < cutoff_date]
    logger.debug(f"Checking outdated recordings against cutoff date {cutoff_date}:")
    for filename, recording_date in downloaded_recordings:
        logger.debug(f"Recording: {filename}, Date: {recording_date}, Outdated: {recording_date < cutoff_date}")
    return outdated_recordings

def prepare_destination(destination, grouping):
    """prepares the destination, ensuring it's valid and removing excess recordings"""
    # optionally removes outdated recordings
    if cutoff_date:
        outdated_recordings = get_outdated_recordings(destination, grouping)

        for outdated_recording in outdated_recordings:
            if dry_run:
                logger.info("DRY RUN Would remove outdated recording : %s", outdated_recording)
                continue

            logger.info("Removing outdated recording : %s", outdated_recording)

            outdated_recording_glob = "%s.*" % os.path.splitext(outdated_recording)[0]
            outdated_filepath_glob = get_filepath(destination, group_name_globs[grouping], outdated_recording_glob)

            # Log the actual files in the directory for comparison
            actual_files = glob.glob(get_filepath(destination, group_name_globs[grouping], "*"))
            logger.debug(f"Actual files in directory: {actual_files}")

            outdated_filepaths = glob.glob(outdated_filepath_glob)

            for outdated_filepath in outdated_filepaths:
                logger.debug(f"Attempting to remove file: {outdated_filepath}")
                if os.path.exists(outdated_filepath):
                    try:
                        os.remove(outdated_filepath)
                        logger.info(f"Successfully removed old file: {outdated_filepath}")
                    except OSError as e:
                        logger.error(f"Error removing file {outdated_filepath}: {e}")
                else:
                    logger.warning(f"File not found, could not remove: {outdated_filepath}")
def sync(address, destination, grouping, download_priority, recording_filter, args):
    """synchronizes the recordings at the Viofo dashcam address with the destination directory"""
    logger.info(f"Starting sync process for address: {address}")
    prepare_destination(destination, grouping)

    base_url = f"http://{address}"
    try:
        dashcam_recordings = get_dashcam_filenames(base_url)
    except (RuntimeError, UserWarning) as e:
        logger.error(f"Sync process aborted: {e}")
        return False

    logger.debug(f"Sorting recordings based on priority: {download_priority}")
    dashcam_recordings.sort(key=lambda r: r.datetime, reverse=(download_priority == "rdate"))

    if recording_filter:
        logger.debug(f"Applying recording filter: {recording_filter}")
        dashcam_recordings = [r for r in dashcam_recordings if any(f in r.filename for f in recording_filter)]
        logger.info(f"Filtered recordings count: {len(dashcam_recordings)}")

    for recording in dashcam_recordings:
        if cutoff_date and recording.datetime.date() < cutoff_date:
            logger.debug(f"Skipping recording due to cutoff date: {recording.filename}")
            continue
        group_name = get_group_name(recording.datetime, grouping)
        downloaded, _ = download_file(base_url, recording, destination, group_name)
        if downloaded and args.gps_extract:
            destination_filepath = os.path.join(destination, group_name, recording.filename) if group_name else os.path.join(destination, recording.filename)
            extract_gps_data(destination_filepath)

    logger.info("Sync process completed")
    return True
    logger.info(f"Starting sync process for address: {address}")
    prepare_destination(destination, grouping)

    base_url = f"http://{address}"
    try:
        dashcam_recordings = get_dashcam_filenames(base_url)
    except (RuntimeError, UserWarning) as e:
        logger.error(f"Sync process aborted: {e}")
        return False

    logger.debug(f"Sorting recordings based on priority: {download_priority}")
    dashcam_recordings.sort(key=lambda r: r.datetime, reverse=(download_priority == "rdate"))

    if recording_filter:
        logger.debug(f"Applying recording filter: {recording_filter}")
        dashcam_recordings = [r for r in dashcam_recordings if any(f in r.filename for f in recording_filter)]
        logger.info(f"Filtered recordings count: {len(dashcam_recordings)}")

    for recording in dashcam_recordings:
        if cutoff_date and recording.datetime.date() < cutoff_date:
            logger.debug(f"Skipping recording due to cutoff date: {recording.filename}")
            continue
        group_name = get_group_name(recording.datetime, grouping)
        downloaded, _ = download_file(base_url, recording, destination, group_name)
        if downloaded:
            destination_filepath = os.path.join(destination, group_name, recording.filename) if group_name else os.path.join(destination, recording.filename)
            extract_gps_data(destination_filepath)

    logger.info("Sync process completed")
    return True

def ensure_destination(destination):
    """ensures the destination directory exists, creates if not, verifies it's writeable"""
    if not os.path.exists(destination):
        os.makedirs(destination)
    elif not os.path.isdir(destination):
        raise RuntimeError(f"Download destination is not a directory : {destination}")
    elif not os.access(destination, os.W_OK):
        raise RuntimeError(f"Download destination directory not writable : {destination}")

def get_group_name(recording_datetime, grouping):
    """determines the group name for a given recording according to the indicated grouping"""
    if grouping == "daily":
        return recording_datetime.strftime("%Y-%m-%d")
    elif grouping == "weekly":
        return (recording_datetime - datetime.timedelta(days=recording_datetime.weekday())).strftime("%Y-%m-%d")
    elif grouping == "monthly":
        return recording_datetime.strftime("%Y-%m")
    elif grouping == "yearly":
        return recording_datetime.strftime("%Y")
    else:
        return None

def to_natural_speed(speed_bps):
    """returns a natural representation of a given download speed in bps"""
    for unit in ['bps', 'Kbps', 'Mbps', 'Gbps']:
        if speed_bps < 1000.0:
            return f"{speed_bps:.1f}{unit}"
        speed_bps /= 1000.0
    return f"{speed_bps:.1f}Tbps"

# GPS Extraction Functions
def fix_time(hour, minute, second, year, month, day):
    return f"{year+2000:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"

def fix_coordinates(hemisphere, coordinate):
    minutes = coordinate % 100.0
    degrees = coordinate - minutes
    coordinate = degrees / 100.0 + (minutes / 60.0)
    return -1 * float(coordinate) if hemisphere in ['S', 'W'] else float(coordinate)

def fix_speed(speed):
    return speed * 0.514444

def get_atom_info(eight_bytes):
    try:
        atom_size, atom_type = struct.unpack('>I4s', eight_bytes)
        return int(atom_size), atom_type.decode()
    except (struct.error, UnicodeDecodeError):
        return 0, ''

def get_gps_atom_info(eight_bytes):
    atom_pos, atom_size = struct.unpack('>II', eight_bytes)
    return int(atom_pos), int(atom_size)

def get_gps_data(data):
    gps = {
        'DT': {
            'Year': None, 'Month': None, 'Day': None,
            'Hour': None, 'Minute': None, 'Second': None, 'DT': None
        },
        'Loc': {
            'Lat': {'Raw': None, 'Hemi': None, 'Float': None},
            'Lon': {'Raw': None, 'Hemi': None, 'Float': None},
            'Speed': None, 'Bearing': None,
        },
    }
    
    offset = 0
    hour, minute, second, year, month, day = struct.unpack_from('<IIIIII', data, offset)
    offset += 24
    active, lat_hemi, lon_hemi = struct.unpack_from('<ccc', data, offset)
    offset += 4
    lat_raw, lon_raw, speed, bearing = struct.unpack_from('<ffff', data, offset)

    gps['DT']['Hour'], gps['DT']['Minute'], gps['DT']['Second'] = hour, minute, second
    gps['DT']['Year'], gps['DT']['Month'], gps['DT']['Day'] = year, month, day
    gps['DT']['DT'] = fix_time(hour, minute, second, year, month, day)

    gps['Loc']['Lat']['Hemi'] = lat_hemi.decode()
    gps['Loc']['Lon']['Hemi'] = lon_hemi.decode()
    gps['Loc']['Lat']['Raw'] = lat_raw
    gps['Loc']['Lon']['Raw'] = lon_raw
    gps['Loc']['Lat']['Float'] = fix_coordinates(gps['Loc']['Lat']['Hemi'], gps['Loc']['Lat']['Raw'])
    gps['Loc']['Lon']['Float'] = fix_coordinates(gps['Loc']['Lon']['Hemi'], gps['Loc']['Lon']['Raw'])
    gps['Loc']['Speed'] = fix_speed(speed)
    gps['Loc']['Bearing'] = bearing

    return gps

def get_gps_atom(gps_atom_info, f):
    atom_pos, atom_size = gps_atom_info
    logger.debug(f"Atom pos = {atom_pos:x}, atom size = {atom_size:x}")
    try:
        f.seek(atom_pos)
        data = f.read(atom_size)
    except OverflowError as e:
        logger.error(f"Skipping at {atom_pos:x}: seek or read error. Error: {str(e)}")
        return None

    expected_type, expected_magic = 'free', 'GPS '
    atom_size1, atom_type, magic = struct.unpack_from('>I4s4s', data)
    try:
        atom_type = atom_type.decode()
        magic = magic.decode()
        if atom_size != atom_size1 or atom_type != expected_type or magic != expected_magic:
            logger.error(f"Error! skipping atom at {atom_pos:x} (expected size:{atom_size}, actual size:{atom_size1}, expected type:{expected_type}, actual type:{atom_type}, expected magic:{expected_magic}, actual magic:{magic})!")
            return None
    except UnicodeDecodeError as e:
        logger.error(f"Skipping at {atom_pos:x}: garbage atom type or magic. Error: {str(e)}")
        return None

    return get_gps_data(data[12:])

def parse_moov(in_fh):
    gps_data = []
    offset = 0
    while True:
        atom_size, atom_type = get_atom_info(in_fh.read(8))
        if atom_size == 0:
            break

        if atom_type == 'moov':
            logger.debug("Found the 'moov' atom.")
            sub_offset = offset + 8
            while sub_offset < (offset + atom_size):
                sub_atom_size, sub_atom_type = get_atom_info(in_fh.read(8))

                if sub_atom_type == 'gps ':
                    logger.debug("Found the gps chunk descriptor atom.")
                    gps_offset = 16 + sub_offset  # +16 = skip headers
                    in_fh.seek(gps_offset, 0)
                    while gps_offset < (sub_offset + sub_atom_size):
                        data = get_gps_atom(get_gps_atom_info(in_fh.read(8)), in_fh)
                        if data:
                            gps_data.append(data)
                        gps_offset += 8
                        in_fh.seek(gps_offset, 0)

                sub_offset += sub_atom_size
                in_fh.seek(sub_offset, 0)

        offset += atom_size
        in_fh.seek(offset, 0)
    return gps_data

def generate_gpx(gps_data, out_file):
    gpx = '<?xml version="1.0" encoding="UTF-8"?>\n'
    gpx += '<gpx version="1.0"\n'
    gpx += '\tcreator="Viofo GPS Extractor"\n'
    gpx += '\txmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
    gpx += '\txmlns="http://www.topografix.com/GPX/1/0"\n'
    gpx += '\txsi:schemaLocation="http://www.topografix.com/GPX/1/0 http://www.topografix.com/GPX/1/0/gpx.xsd">\n'
    gpx += f"\t<name>{out_file}</name>\n"
    gpx += f"\t<trk><name>{out_file}</name><trkseg>\n"
    for gps in gps_data:
        if gps:
            gpx += f"\t\t<trkpt lat=\"{gps['Loc']['Lat']['Float']}\" lon=\"{gps['Loc']['Lon']['Float']}\">"
            gpx += f"<time>{gps['DT']['DT']}</time>"
            gpx += f"<speed>{gps['Loc']['Speed']}</speed>"
            gpx += f"<course>{gps['Loc']['Bearing']}</course></trkpt>\n"
    gpx += '\t</trkseg></trk>\n'
    gpx += '</gpx>\n'
    return gpx

def extract_gps_data(file_path):
    logger.info(f"Extracting GPS data from {file_path}")
    
    gps_data = []
    with open(file_path, "rb") as in_fh:
        gps_data = parse_moov(in_fh)

    logger.info(f"Found {len(gps_data)} GPS data points.")

    if gps_data:
        gpx_file = file_path + ".gpx"
        gpx_content = generate_gpx(gps_data, os.path.basename(gpx_file))
        with open(gpx_file, "w") as f:
            logger.info(f"Writing GPS data to output file '{gpx_file}'.")
            f.write(gpx_content)
    else:
        logger.warning("No GPS data found in the file.")

def parse_args():
    parser = argparse.ArgumentParser(
        description="Synchronizes Viofo dashcam recordings or monitors continuously."
    )
    parser.add_argument("address", help="Dashcam IP address or hostname")
    parser.add_argument("-d", "--destination", default=os.getcwd(),
                        help="Destination directory for downloads")
    parser.add_argument("-g", "--grouping", choices=["none","daily","weekly","monthly","yearly"],
                        default="none", help="Group recordings by time period")
    parser.add_argument("-p", "--priority", choices=["date","rdate"], default="date",
                        help="Download priority: date or rdate")
    parser.add_argument("-f", "--filter", nargs="+",
                        help="Filter recordings by filename pattern")
    parser.add_argument("-k", "--keep",
                        help="Keep recordings for <number>[d|w]")
    parser.add_argument("-u", "--max-used-disk", type=int, choices=range(5,99),
                        default=90, metavar="DISK%", help="Max disk usage percent")
    parser.add_argument("-t", "--timeout", type=float, default=10.0,
                        help="Connection timeout (seconds)")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity (DEBUG)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Quiet mode (errors only)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Perform a trial run without downloading")
    parser.add_argument("--cron", action="store_true",
                        help="Cron-style logging")
    parser.add_argument("--gps-extract", action="store_true",
                        help="Extract GPS data to .gpx")
    parser.add_argument("--run-once", action="store_true",
                        help="Do a single sync then exit")
    parser.add_argument("--monitor", action="store_true",
                        help="Long-running monitor mode (no cron)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args()

def monitor_loop(address, destination, grouping, priority, recording_filter, args):
    """Long-running loop: HEAD-check for new/grown files, then download only changed ones."""
    logger.info("Entering monitor loop; press Ctrl+C to exit")
    last_sizes = {}  # filename → last observed remote size
    base_url = f"http://{address}"
    while True:
        # 1) Quick HEAD on file list endpoint to check availability
        try:
            req = urllib.request.Request(f"{base_url}/?custom=1&cmd=3015&par=1", method="HEAD")
            urllib.request.urlopen(req, timeout=socket_timeout)
        except Exception as e:
            logger.warning("Dashcam unreachable: %s; retrying in 30s", e)
            time.sleep(30)
            continue

        # 2) Fetch full file list
        try:
            recordings = get_dashcam_filenames(base_url)
        except Exception as e:
            logger.error("Failed to fetch list: %s; retrying in 30s", e)
            time.sleep(30)
            continue

        to_download = []
        # 3) For each recording, HEAD to check if new or grown
        for rec in recordings:
            cleaned = rec.filepath.replace('A:', '').replace('\\','/')
            url = f"{base_url}/{cleaned}"
            try:
                req = urllib.request.Request(url, method="HEAD")
                with urllib.request.urlopen(req, timeout=socket_timeout) as resp:
                    remote_size = int(resp.getheader("Content-Length","0"))
            except Exception:
                continue

            prev = last_sizes.get(rec.filename)
            if prev is None or prev != remote_size:
                last_sizes[rec.filename] = remote_size
                to_download.append(rec)

        # 4) Download changed
        if to_download:
            logger.info("Detected %d new/updated files", len(to_download))
            for rec in to_download:
                grp = get_group_name(rec.datetime, grouping)
                downloaded, _ = download_file(base_url, rec, destination, grp)
                if downloaded and args.gps_extract:
                    extract_gps_data(os.path.join(destination, grp or "", rec.filename))
        else:
            logger.debug("No changes detected")

        time.sleep(30)  # polling interval; you can make this configurable

def run():
    global dry_run, max_disk_used_percent, cutoff_date, socket_timeout

    args = parse_args()
    socket_timeout = args.timeout
    socket.setdefaulttimeout(socket_timeout)

    # logging levels
    if args.quiet:
        logger.setLevel(logging.ERROR)
        cron_logger.setLevel(logging.ERROR)
    elif args.cron:
        logger.setLevel(logging.WARNING)
        cron_logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.DEBUG if args.verbose>0 else logging.INFO)

    dry_run = args.dry_run

    # compute cutoff_date if --keep used…
    # … (your existing keep logic) …

    if args.monitor:
        monitor_loop(args.address, args.destination,
                     args.grouping, args.priority,
                     args.filter, args)
        return 0

    # otherwise do one sync
    success = sync(args.address, args.destination,
                   args.grouping, args.priority,
                   args.filter, args)
    return 0 if success else 1

if __name__ == "__main__":
    exit(run())