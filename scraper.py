import requests
import os
import re
from urllib.parse import urljoin, urlparse


CANVAS_BASE_URL = "https://canvas.sfu.ca"
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
COURSE_ID = os.getenv("COURSE_ID")
ALLOWED_EXTENSIONS = ['.pptx', '.pdf', '.zip', '.docx', '.py', '.ipynb', '.java', '.txt', '.csv']
DOWNLOAD_DIR = f"canvas_course_{COURSE_ID}_files"


def sanitize_filename(filename):
    """Removes or replaces characters invalid for typical file systems."""
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    sanitized = sanitized.replace(" ", "_")
    return sanitized

def make_api_request(url, session, params=None):
    all_results = []
    next_url = url 

    while next_url:
        try:
            response = session.get(next_url, params=params)
            params = None
            response.raise_for_status()  

            try:
                data = response.json()
                if isinstance(data, list):
                    all_results.extend(data)
                else:
                    print(f"Warning: Unexpected non-list response from {next_url}. Data: {data}")
                    if isinstance(data, dict):
                         all_results.append(data)
                    next_url = None
                    continue 


            except requests.exceptions.JSONDecodeError:
                 print(f"Error: Could not decode JSON from {next_url}")
                 print(f"Response text: {response.text[:500]}...")
                 next_url = None
                 continue 


            next_url = None
            if 'Link' in response.headers:
                links = requests.utils.parse_header_links(response.headers['Link'])
                for link in links:
                    if link.get('rel') == 'next':
                        next_url = link.get('url')
                        break 

        except requests.exceptions.RequestException as e:
            print(f"Error during API request to {next_url or url}: {e}")
            print(f"Response status: {response.status_code if 'response' in locals() else 'N/A'}")
            print(f"Response text: {response.text[:500] if 'response' in locals() else 'N/A'}...")
            return None 

    return all_results


def download_file(url, filename, download_path, session):
    """Downloads a file from a URL to a specified path using streaming."""
    full_path = os.path.join(download_path, filename)
    print(f"  Downloading: {filename}...")
    try:
        with session.get(url, stream=True, allow_redirects=True) as r:
            r.raise_for_status()
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        print(f"  Successfully downloaded: {full_path}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"  Error downloading {filename} from {url}: {e}")
    except OSError as e:
        print(f"  Error saving file {filename} to {full_path}: {e}")
    except Exception as e:
        print(f"  An unexpected error occurred downloading {filename}: {e}")
    return False


if __name__ == "__main__":
    print(f"Starting download process for course ID: {COURSE_ID}")
    print(f"Saving files to directory: {DOWNLOAD_DIR}")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    auth_header = {'Authorization': f'Bearer {ACCESS_TOKEN}'}
    session = requests.Session()
    session.headers.update(auth_header)

    files_to_download = {} 

    print("\nFetching files from 'Files' section...")
    files_url = f"{CANVAS_BASE_URL}/api/v1/courses/{COURSE_ID}/files"
    course_files = make_api_request(files_url, session, params={'per_page': 100})

    if course_files is not None:
        print(f"Found {len(course_files)} potential file entries in 'Files' section.")
        for file_info in course_files:
            if file_info.get('url'): 
                files_to_download[file_info['id']] = {
                    'filename': file_info['display_name'],
                    'url': file_info['url'], 
                    'id': file_info['id']
                }
            else:
                print(f"  Skipping entry without URL (likely a folder): {file_info.get('display_name', 'N/A')}")

    print("\nFetching files from Modules...")
    modules_url = f"{CANVAS_BASE_URL}/api/v1/courses/{COURSE_ID}/modules"
    modules = make_api_request(modules_url, session, params={'include': ['items'], 'per_page': 50})

    if modules is not None:
        print(f"Found {len(modules)} modules.")
        for module in modules:
            print(f"  Checking module: {module['name']}")
            module_items = module.get('items', [])
            if not module_items:
                items_url = f"{CANVAS_BASE_URL}/api/v1/courses/{COURSE_ID}/modules/{module['id']}/items"
                module_items = make_api_request(items_url, session, params={'per_page': 100}) or [] # Ensure it's a list

            for item in module_items:
                if item.get('type') == 'File':
                    file_detail_url = item.get('url')
                    if file_detail_url:
                         print(f"    Found file item: {item.get('title', 'N/A')}. Fetching details...")
                         file_details_list = make_api_request(file_detail_url, session)
                         if file_details_list:
                             file_info = file_details_list[0] if isinstance(file_details_list, list) else file_details_list

                             if isinstance(file_info, dict) and file_info.get('url'): # Check if it's a dict and has a URL
                                 if file_info['id'] not in files_to_download:
                                     files_to_download[file_info['id']] = {
                                        'filename': file_info['display_name'],
                                        'url': file_info['url'],
                                        'id': file_info['id']
                                    }
                                     print(f"      Added file: {file_info['display_name']}")
                                 else:
                                     print(f"      Skipping duplicate file: {file_info['display_name']}")
                             else:
                                print(f"    Warning: Could not get valid file details from {file_detail_url}. Data: {file_info}")
                         else:
                            print(f"    Warning: Failed to fetch file details from {file_detail_url}")

    print(f"\nFound a total of {len(files_to_download)} unique file entries.")
    print("Filtering by allowed extensions:", ALLOWED_EXTENSIONS)

    download_count = 0
    skipped_count = 0
    error_count = 0

    if not files_to_download:
        print("\nNo files found matching the criteria or accessible via API.")
    else:
        print("\nStarting downloads...")
        for file_id, file_info in files_to_download.items():
            original_filename = file_info['filename']
            download_url = file_info['url']

            file_ext = os.path.splitext(original_filename)[1].lower()
            if file_ext in ALLOWED_EXTENSIONS:
                sanitized = sanitize_filename(original_filename)
                if download_file(download_url, sanitized, DOWNLOAD_DIR, session):
                    download_count += 1
                else:
                    error_count += 1
            else:
                skipped_count += 1

    print("\n--- Download Summary ---")
    print(f"Successfully downloaded: {download_count}")
    print(f"Skipped (wrong extension): {skipped_count}")
    print(f"Errors during download: {error_count}")
    print(f"Files saved to: {os.path.abspath(DOWNLOAD_DIR)}")
    print("------------------------")
