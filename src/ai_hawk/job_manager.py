import json
import os
import random
import time
from itertools import product
from pathlib import Path
import traceback
from turtle import color

from inputimeout import inputimeout, TimeoutOccurred
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By


from ai_hawk.linkedIn_easy_applier import AIHawkEasyApplier
from config import JOB_MAX_APPLICATIONS, JOB_MIN_APPLICATIONS, MINIMUM_WAIT_TIME_IN_SECONDS

from src.job import Job
from src.logging import logger

import urllib.parse
from src.regex_utils import generate_regex_patterns_for_blacklisting
from src.db import JobRepository
import re

import utils.browser_utils as browser_utils
import utils.time_utils


class EnvironmentKeys:
    def __init__(self):
        logger.debug("Initializing EnvironmentKeys")
        self.skip_apply = self._read_env_key_bool("SKIP_APPLY")
        self.disable_description_filter = self._read_env_key_bool("DISABLE_DESCRIPTION_FILTER")
        logger.debug(f"EnvironmentKeys initialized: skip_apply={self.skip_apply}, disable_description_filter={self.disable_description_filter}")

    @staticmethod
    def _read_env_key(key: str) -> str:
        value = os.getenv(key, "")
        logger.debug(f"Read environment key {key}: {value}")
        return value

    @staticmethod
    def _read_env_key_bool(key: str) -> bool:
        value = os.getenv(key) == "True"
        logger.debug(f"Read environment key {key} as bool: {value}")
        return value


class AIHawkJobManager:
    def __init__(self, driver):
        logger.debug("Initializing AIHawkJobManager")
        self.driver = driver
        self.set_old_answers = set()
        self.easy_applier_component = None
        logger.debug("AIHawkJobManager initialized successfully")

    def set_parameters(self, parameters):
        logger.debug("Setting parameters for AIHawkJobManager")
        self.company_blacklist = parameters.get('company_blacklist', []) or []
        self.title_blacklist = parameters.get('title_blacklist', []) or []
        self.location_blacklist = parameters.get('location_blacklist', []) or []
        self.positions = parameters.get('positions', [])
        self.locations = parameters.get('locations', [])
        self.apply_once_at_company = parameters.get('apply_once_at_company', False)
        self.base_search_url = self.get_base_search_url(parameters)
        self.seen_jobs = []

        self.min_applicants = JOB_MIN_APPLICATIONS
        self.max_applicants = JOB_MAX_APPLICATIONS

        # Generate regex patterns from blacklist lists
        self.title_blacklist_patterns = generate_regex_patterns_for_blacklisting(self.title_blacklist)
        self.company_blacklist_patterns = generate_regex_patterns_for_blacklisting(self.company_blacklist)
        self.location_blacklist_patterns = generate_regex_patterns_for_blacklisting(self.location_blacklist)

        resume_path = parameters.get('uploads', {}).get('resume', None)
        self.resume_path = Path(resume_path) if resume_path and Path(resume_path).exists() else None
        self.output_file_directory = Path(parameters['outputFileDirectory'])
        self.env_config = EnvironmentKeys()
        logger.debug("Parameters set successfully")

    def set_gpt_answerer(self, gpt_answerer):
        logger.debug("Setting GPT answerer")
        self.gpt_answerer = gpt_answerer

    def set_resume_generator_manager(self, resume_generator_manager):
        logger.debug("Setting resume generator manager")
        self.resume_generator_manager = resume_generator_manager

    def start_collecting_data(self):
        """DEPRECATED: Old JSON-based collection. Use start_collecting_to_db() instead."""
        pass

    def start_collecting_to_db(self):
        """Scrape ALL job listings and store them in a SQLite database."""
        logger.info("Starting job collection to SQLite database", color="yellow")
        job_repo = JobRepository(db_path=str(self.output_file_directory.parent / "jobs.db"))
        searches = list(product(self.positions, self.locations))
        random.shuffle(searches)
        page_sleep = 0
        minimum_time = 60 * 2
        minimum_page_time = time.time() + minimum_time
        total_new = 0
        total_skipped = 0

        for position, location in searches:
            location_url = "&location=" + location
            job_page_number = -1
            logger.info(f"Collecting jobs for '{position}' in '{location}'.", color="yellow")
            try:
                while True:
                    page_sleep += 1
                    job_page_number += 1
                    logger.info(f"Going to job page {job_page_number}", color="yellow")
                    self.next_job_page(position, location_url, job_page_number)
                    utils.time_utils.medium_sleep()

                    try:
                        jobs_on_page = self.get_jobs_from_page(scroll=True)
                        if not jobs_on_page:
                            logger.info("No more jobs found on this page. Moving to next search.", color="yellow")
                            break
                    except Exception as e:
                        logger.error(f"Failed to retrieve jobs: {e}")
                        break

                    for job_tile in jobs_on_page:
                        try:
                            job = self.job_tile_to_job(job_tile)
                            if not job.link:
                                continue
                            if job_repo.insert_job(job):
                                total_new += 1
                            else:
                                total_skipped += 1
                        except Exception as e:
                            logger.warning(f"Failed to process a job tile: {e}")
                            continue

                    logger.info(f"Page {job_page_number} done. New: {total_new}, Already existed: {total_skipped}", color="yellow")

                    time_left = minimum_page_time - time.time()
                    if time_left > 0:
                        try:
                            user_input = inputimeout(
                                prompt=f"Sleeping for {time_left:.0f}s. Press 'y' to skip: ",
                                timeout=60).strip().lower()
                        except TimeoutOccurred:
                            user_input = ''
                        if user_input != 'y':
                            time.sleep(max(0, time_left))
                    minimum_page_time = time.time() + minimum_time

                    if page_sleep % 5 == 0:
                        sleep_time = random.randint(5, 20)
                        logger.info(f"Anti-throttle sleep: {sleep_time}s", color="yellow")
                        time.sleep(sleep_time)
                        page_sleep += 1
            except Exception as e:
                logger.error(f"Unexpected error during collection: {e}")
                continue

        logger.info(f"Collection complete. Total new jobs: {total_new}, Already existed: {total_skipped}. DB: {job_repo.db_path}", color="yellow")

    # ---- AUTO-APPLY DISABLED ----
    # The start_applying() and apply_jobs() methods have been commented out.
    # The bot now only collects job listings into a SQLite database.
    # To re-enable, uncomment these methods and update main.py / bot_facade.py.

    # def start_applying(self):
    #     logger.debug("Starting job application process")
    #     self.easy_applier_component = AIHawkEasyApplier(self.driver, self.resume_path, self.set_old_answers,
    #                                                       self.gpt_answerer, self.resume_generator_manager)
    #     searches = list(product(self.positions, self.locations))
    #     random.shuffle(searches)
    #     page_sleep = 0
    #     minimum_time = MINIMUM_WAIT_TIME_IN_SECONDS
    #     minimum_page_time = time.time() + minimum_time
    #     for position, location in searches:
    #         location_url = "&location=" + location
    #         job_page_number = -1
    #         try:
    #             while True:
    #                 page_sleep += 1
    #                 job_page_number += 1
    #                 self.next_job_page(position, location_url, job_page_number)
    #                 utils.time_utils.medium_sleep()
    #                 try:
    #                     jobs = self.get_jobs_from_page(scroll=True)
    #                     if not jobs: break
    #                 except Exception as e:
    #                     break
    #                 try:
    #                     self.apply_jobs()
    #                 except Exception as e:
    #                     continue
    #         except Exception as e:
    #             continue

    def get_jobs_from_page(self, scroll=False):
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        try:
            no_jobs_element = self.driver.find_element(By.CLASS_NAME, 'jobs-search-two-pane__no-results-banner--expand')
            if 'No matching jobs found' in no_jobs_element.text or 'unfortunately, things aren' in self.driver.page_source.lower():
                logger.debug("No matching jobs found on this page, skipping.")
                return []
        except NoSuchElementException:
            pass

        try:
            # Scroll the main page to load all lazy-loaded job cards
            if scroll:
                try:
                    scrollable = self.driver.find_element(By.TAG_NAME, 'html')
                    browser_utils.scroll_slow(self.driver, scrollable, step=300, reverse=False)
                    browser_utils.scroll_slow(self.driver, scrollable, step=300, reverse=True)
                except Exception as e:
                    logger.debug(f"Scroll attempt: {e}")

            # Wait for at least one job link to appear on the page
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/jobs/view/')]"))
                )
            except Exception:
                logger.warning("No job links (/jobs/view/) found on page after waiting 10s.")
                return []

            # Find ALL <a> elements whose href contains /jobs/view/
            job_links = self.driver.find_elements(By.XPATH, "//a[contains(@href, '/jobs/view/')]")
            logger.debug(f"Found {len(job_links)} raw job link elements on page")

            if not job_links:
                return []

            # Deduplicate by href and get the parent card (ancestor <li>) for each link
            seen_hrefs = set()
            job_cards = []
            for link_el in job_links:
                href = link_el.get_attribute('href')
                if not href:
                    continue
                clean_href = href.split('?')[0]
                if clean_href in seen_hrefs:
                    continue
                seen_hrefs.add(clean_href)

                # Walk up to the nearest <li> ancestor to get the full job card
                try:
                    card = link_el.find_element(By.XPATH, "./ancestor::li")
                    job_cards.append(card)
                except NoSuchElementException:
                    # If no <li> ancestor, use the link element itself
                    job_cards.append(link_el)

            logger.info(f"Found {len(job_cards)} unique job cards on page")
            return job_cards

        except Exception as e:
            logger.error(f"Error while fetching job elements: {e} {traceback.format_exc()}")
            return []

    def read_jobs(self):

        job_element_list = self.get_jobs_from_page()
        job_list = [self.job_tile_to_job(job_element) for job_element in job_element_list] 
        for job in job_list:            
            if self.is_blacklisted(job.title, job.company, job.link, job.location):
                logger.info(f"Blacklisted {job.title} at {job.company} in {job.location}, skipping...")
                self.write_to_file(job, "skipped")
                continue
            try:
                self.write_to_file(job,'data')
            except Exception as e:
                self.write_to_file(job, "failed")
                continue

    def apply_jobs(self):
        job_element_list = self.get_jobs_from_page()

        job_list = [self.job_tile_to_job(job_element) for job_element in job_element_list]

        for job in job_list:

            logger.debug(f"Starting applicant for job: {job.title} at {job.company}")
            #TODO fix apply threshold
            """
                # Initialize applicants_count as None
                applicants_count = None

                # Iterate over each job insight element to find the one containing the word "applicant"
                for element in job_insight_elements:
                    logger.debug(f"Checking element text: {element.text}")
                    if "applicant" in element.text.lower():
                        # Found an element containing "applicant"
                        applicants_text = element.text.strip()
                        logger.debug(f"Applicants text found: {applicants_text}")

                        # Extract numeric digits from the text (e.g., "70 applicants" -> "70")
                        applicants_count = ''.join(filter(str.isdigit, applicants_text))
                        logger.debug(f"Extracted applicants count: {applicants_count}")

                        if applicants_count:
                            if "over" in applicants_text.lower():
                                applicants_count = int(applicants_count) + 1  # Handle "over X applicants"
                                logger.debug(f"Applicants count adjusted for 'over': {applicants_count}")
                            else:
                                applicants_count = int(applicants_count)  # Convert the extracted number to an integer
                        break

                # Check if applicants_count is valid (not None) before performing comparisons
                if applicants_count is not None:
                    # Perform the threshold check for applicants count
                    if applicants_count < self.min_applicants or applicants_count > self.max_applicants:
                        logger.debug(f"Skipping {job.title} at {job.company}, applicants count: {applicants_count}")
                        self.write_to_file(job, "skipped_due_to_applicants")
                        continue  # Skip this job if applicants count is outside the threshold
                    else:
                        logger.debug(f"Applicants count {applicants_count} is within the threshold")
                else:
                    # If no applicants count was found, log a warning but continue the process
                    logger.warning(
                        f"Applicants count not found for {job.title} at {job.company}, continuing with application.")
            except NoSuchElementException:
                # Log a warning if the job insight elements are not found, but do not stop the job application process
                logger.warning(
                    f"Applicants count elements not found for {job.title} at {job.company}, continuing with application.")
            except ValueError as e:
                # Handle errors when parsing the applicants count
                logger.error(f"Error parsing applicants count for {job.title} at {job.company}: {e}")
            except Exception as e:
                # Catch any other exceptions to ensure the process continues
                logger.error(
                    f"Unexpected error during applicants count processing for {job.title} at {job.company}: {e}")

            # Continue with the job application process regardless of the applicants count check
            """
        

            if self.is_previously_failed_to_apply(job.link):
                logger.debug(f"Previously failed to apply for {job.title} at {job.company}, skipping...")
                continue
            if self.is_blacklisted(job.title, job.company, job.link, job.location):
                logger.debug(f"Job blacklisted: {job.title} at {job.company} in {job.location}")
                self.write_to_file(job, "skipped", "Job blacklisted")
                continue
            if self.is_already_applied_to_job(job.title, job.company, job.link):
                self.write_to_file(job, "skipped", "Already applied to this job")
                continue
            if self.is_already_applied_to_company(job.company):
                self.write_to_file(job, "skipped", "Already applied to this company")
                continue
            try:
                if job.apply_method not in {"Continue", "Applied", "Apply"}:
                    self.easy_applier_component.job_apply(job)
                    self.write_to_file(job, "success")
                    logger.debug(f"Applied to job: {job.title} at {job.company}")
            except Exception as e:
                logger.error(f"Failed to apply for {job.title} at {job.company}: {e}",exc_info=True)
                self.write_to_file(job, "failed", f"Application error: {str(e)}")
                continue

    def write_to_file(self, job : Job, file_name, reason=None):
        logger.debug(f"Writing job application result to file: {file_name}")
        pdf_path = Path(job.resume_path).resolve()
        pdf_path = pdf_path.as_uri()
        data = {
            "company": job.company,
            "job_title": job.title,
            "link": job.link,
            "job_recruiter": job.recruiter_link,
            "job_location": job.location,
            "pdf_path": pdf_path
        }
        
        if reason:
            data["reason"] = reason
            
        file_path = self.output_file_directory / f"{file_name}.json"
        if not file_path.exists():
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump([data], f, indent=4)
                logger.debug(f"Job data written to new file: {file_name}")
        else:
            with open(file_path, 'r+', encoding='utf-8') as f:
                try:
                    existing_data = json.load(f)
                except json.JSONDecodeError:
                    logger.error(f"JSON decode error in file: {file_path}")
                    existing_data = []
                existing_data.append(data)
                f.seek(0)
                json.dump(existing_data, f, indent=4)
                f.truncate()
                logger.debug(f"Job data appended to existing file: {file_name}")

    def get_base_search_url(self, parameters):
        logger.debug("Constructing base search URL")
        url_parts = []
        working_type_filter = []
        if parameters.get("onsite") == True:
            working_type_filter.append("1")
        if parameters.get("remote") == True:
            working_type_filter.append("2")
        if parameters.get("hybrid") == True:
            working_type_filter.append("3")

        if working_type_filter:
            url_parts.append(f"f_WT={'%2C'.join(working_type_filter)}")

        experience_levels = [str(i + 1) for i, (level, v) in enumerate(parameters.get('experience_level', {}).items()) if
                             v]
        if experience_levels:
            url_parts.append(f"f_E={','.join(experience_levels)}")
        url_parts.append(f"distance={parameters['distance']}")
        job_types = [key[0].upper() for key, value in parameters.get('jobTypes', {}).items() if value]
        if job_types:
            url_parts.append(f"f_JT={','.join(job_types)}")
        date_mapping = {
            "all_time": "",
            "month": "&f_TPR=r2592000",
            "week": "&f_TPR=r604800",
            "24_hours": "&f_TPR=r86400"
        }
        date_param = next((v for k, v in date_mapping.items() if parameters.get('date', {}).get(k)), "")
        # Removed Easy Apply filter to collect ALL jobs
        # url_parts.append("f_LF=f_AL")  # Easy Apply
        base_url = "&".join(url_parts)
        full_url = f"?{base_url}{date_param}"
        logger.debug(f"Base search URL constructed: {full_url}")
        return full_url

    def next_job_page(self, position, location, job_page):
        logger.debug(f"Navigating to next job page: {position} in {location}, page {job_page}")
        encoded_position = urllib.parse.quote(position)
        self.driver.get(
            f"https://www.linkedin.com/jobs/search/{self.base_search_url}&keywords={encoded_position}{location}&start={job_page * 25}")


    def job_tile_to_job(self, job_tile) -> Job:
        logger.debug("Extracting job information from tile")
        job = Job()

        # --- Extract link (most critical field) ---
        # Strategy: find any <a> tag whose href contains /jobs/view/
        try:
            link_elements = job_tile.find_elements(By.XPATH, ".//a[contains(@href, '/jobs/view/')]")
            if link_elements:
                href = link_elements[0].get_attribute('href')
                if href:
                    job.link = href.split('?')[0]
                    logger.debug(f"Job link extracted: {job.link}")
            
            if not job.link:
                # Fallback: try any <a> with href containing /jobs/
                link_elements = job_tile.find_elements(By.XPATH, ".//a[contains(@href, '/jobs/')]")
                if link_elements:
                    href = link_elements[0].get_attribute('href')
                    if href:
                        job.link = href.split('?')[0]
                        logger.debug(f"Job link extracted (fallback): {job.link}")
        except Exception as e:
            logger.warning(f"Failed to extract job link: {e}")

        # --- Extract title ---
        try:
            # Try the original class first
            job.title = job_tile.find_element(By.CLASS_NAME, 'job-card-list__title').find_element(By.TAG_NAME, 'strong').text
        except NoSuchElementException:
            try:
                # Fallback: get the text from the link element we already found
                if link_elements:
                    title_text = link_elements[0].text.strip()
                    if title_text:
                        job.title = title_text
                        logger.debug(f"Job title extracted from link text: {job.title}")
            except Exception:
                pass
            if not job.title:
                try:
                    # Fallback: find any <strong> or heading inside the tile
                    strong = job_tile.find_elements(By.TAG_NAME, 'strong')
                    if strong:
                        job.title = strong[0].text.strip()
                except Exception:
                    pass
            if not job.title:
                try:
                    # Last resort: get any <a> text that looks like a title
                    all_links = job_tile.find_elements(By.TAG_NAME, 'a')
                    for a in all_links:
                        text = a.text.strip()
                        if text and len(text) > 3:
                            job.title = text
                            break
                except Exception:
                    pass
            if not job.title:
                logger.warning("Job title is missing.")

        logger.debug(f"Job title: {job.title}")

        # --- Extract company ---
        try:
            job.company = job_tile.find_element(By.XPATH, ".//div[contains(@class, 'artdeco-entity-lockup__subtitle')]//span").text
        except NoSuchElementException:
            try:
                # Fallback: look for subtitle spans
                subtitle_spans = job_tile.find_elements(By.XPATH, ".//span[contains(@class, 'subtitle')]")
                if subtitle_spans:
                    job.company = subtitle_spans[0].text.strip()
            except Exception:
                pass
            if not job.company:
                try:
                    # Fallback: look for any element with 'company' in class
                    company_el = job_tile.find_elements(By.XPATH, ".//*[contains(@class, 'company')]")
                    if company_el:
                        job.company = company_el[0].text.strip()
                except Exception:
                    pass
            if not job.company:
                logger.warning("Job company is missing.")

        logger.debug(f"Job company: {job.company}")

        # --- Extract job ID from URL ---
        if job.link:
            try:
                match = re.search(r'/jobs/view/(\d+)', job.link)
                if match:
                    job.id = match.group(1)
                    logger.debug(f"Job ID extracted: {job.id}")
                else:
                    logger.debug(f"Job ID not found in link: {job.link}")
            except Exception as e:
                logger.warning(f"Failed to extract job ID: {e}")

        # --- Extract location ---
        try:
            job.location = job_tile.find_element(By.CLASS_NAME, 'job-card-container__metadata-item').text
        except NoSuchElementException:
            try:
                # Fallback: look for metadata or location-related elements
                meta_items = job_tile.find_elements(By.XPATH, ".//*[contains(@class, 'metadata')]")
                if meta_items:
                    job.location = meta_items[0].text.strip()
            except Exception:
                pass
            if not job.location:
                logger.debug("Job location is missing.")

        # --- Extract apply method (optional, not critical for collection) ---
        try:
            job_state = job_tile.find_element(By.XPATH, ".//ul[contains(@class, 'job-card-list__footer-wrapper')]//li[contains(@class, 'job-card-container__apply-method')]").text
            job.apply_method = job_state
        except NoSuchElementException:
            try:
                job_state = job_tile.find_element(By.XPATH, ".//ul[contains(@class, 'job-card-list__footer-wrapper')]//li[contains(@class, 'job-card-container__footer-job-state')]").text
                job.apply_method = job_state
            except NoSuchElementException:
                # Not critical for collection mode - just leave it empty
                job.apply_method = ""

        return job

    def is_blacklisted(self, job_title, company, link, job_location):
        logger.debug(f"Checking if job is blacklisted: {job_title} at {company} in {job_location}")
        title_blacklisted = any(re.search(pattern, job_title, re.IGNORECASE) for pattern in self.title_blacklist_patterns)
        company_blacklisted = any(re.search(pattern, company, re.IGNORECASE) for pattern in self.company_blacklist_patterns)
        location_blacklisted = any(re.search(pattern, job_location, re.IGNORECASE) for pattern in self.location_blacklist_patterns)
        link_seen = link in self.seen_jobs
        is_blacklisted = title_blacklisted or company_blacklisted or location_blacklisted or link_seen
        logger.debug(f"Job blacklisted status: {is_blacklisted}")

        return is_blacklisted

    def is_already_applied_to_job(self, job_title, company, link):
        link_seen = link in self.seen_jobs
        if link_seen:
            logger.debug(f"Already applied to job: {job_title} at {company}, skipping...")
        return link_seen

    def is_already_applied_to_company(self, company):
        if not self.apply_once_at_company:
            return False

        output_files = ["success.json"]
        for file_name in output_files:
            file_path = self.output_file_directory / file_name
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        existing_data = json.load(f)
                        for applied_job in existing_data:
                            if applied_job['company'].strip().lower() == company.strip().lower():
                                logger.debug(
                                    f"Already applied at {company} (once per company policy), skipping...")
                                return True
                    except json.JSONDecodeError:
                        continue
        return False

    def is_previously_failed_to_apply(self, link):
        file_name = "failed"
        file_path = self.output_file_directory / f"{file_name}.json"

        if not file_path.exists():
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump([], f)

        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                existing_data = json.load(f)
            except json.JSONDecodeError:
                logger.error(f"JSON decode error in file: {file_path}")
                return False
            
        for data in existing_data:
            data_link = data['link']
            if data_link == link:
                return True
                
        return False
