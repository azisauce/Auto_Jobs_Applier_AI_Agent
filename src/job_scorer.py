import json
import re
import time
import traceback

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

import ai_hawk.llm.prompts as prompts
from ai_hawk.llm.llm_manager import AIAdapter, LoggerChatModel
from src.db import JobRepository
from src.logging import logger


class JobScorer:
    """Scores collected jobs using LLM analysis and LinkedIn connection detection."""

    def __init__(self, driver, parameters: dict, llm_api_key: str, resume_text: str):
        self.driver = driver
        self.parameters = parameters
        self.resume_text = resume_text
        self.positions = parameters.get('positions', [])
        self.locations = parameters.get('locations', [])

        # Initialize LLM
        self.ai_adapter = AIAdapter(parameters, llm_api_key)
        self.llm = LoggerChatModel(self.ai_adapter)

        # Initialize DB
        self.job_repo = JobRepository(db_path="data_folder/jobs.db")

        logger.info("JobScorer initialized", color="yellow")

    def score_all_unscored(self):
        """Score all jobs in the DB that haven't been scored yet."""
        unscored = self.job_repo.get_unscored_jobs()
        total = len(unscored)

        if total == 0:
            logger.info("No unscored jobs found. Run collection first.", color="yellow")
            return

        logger.info(f"Found {total} unscored jobs. Starting scoring...", color="yellow")

        scored_count = 0
        failed_count = 0

        for i, job_row in enumerate(unscored):
            link = job_row['link']
            title = job_row['title'] or 'Unknown'
            company = job_row['company'] or 'Unknown'
            location = job_row['location'] or 'Unknown'

            logger.info(f"[{i+1}/{total}] Scoring: {title} at {company}", color="yellow")

            try:
                # Step 1: Fetch job description if not already fetched
                description = job_row.get('description') or ''
                if not description:
                    description = self._fetch_job_description(link)
                    if description:
                        self.job_repo.update_job_description(link, description)
                    else:
                        logger.warning(f"Could not fetch description for: {title}")
                        description = f"Job Title: {title}\nCompany: {company}\nLocation: {location}"

                # Step 2: Score with LLM
                score_data = self._score_with_llm(title, company, location, description)

                # Step 3: Check for connections
                has_connections, connection_count = self._check_connections(company)

                # Step 4: Calculate total score with connection bonus
                connection_bonus = min(connection_count * 3, 15) if has_connections else 0
                base_score = sum(v for k, v in score_data.items() if k != 'reasoning')
                total_score = min(base_score + connection_bonus, 100)

                score_data['connection_bonus'] = connection_bonus

                # Step 5: Store in DB
                self.job_repo.update_job_score(
                    link=link,
                    score=total_score,
                    score_breakdown=score_data,
                    has_connections=has_connections,
                    connection_count=connection_count
                )

                scored_count += 1
                logger.info(
                    f"  Score: {total_score}/100 | Skills: {score_data.get('skills_match', 0)} | "
                    f"Exp: {score_data.get('experience_fit', 0)} | "
                    f"Connections: {connection_count} (+{connection_bonus})",
                    color="yellow"
                )

                # Anti-throttle
                time.sleep(2)

            except Exception as e:
                failed_count += 1
                logger.error(f"  Failed to score: {e}")
                continue

        logger.info(
            f"\nScoring complete! Scored: {scored_count}, Failed: {failed_count}",
            color="yellow"
        )
        self._print_top_jobs()

    def _fetch_job_description(self, link: str) -> str:
        """Navigate to the job detail page and extract the description."""
        try:
            self.driver.get(link)
            time.sleep(3)

            # Wait for the description container
            try:
                WebDriverWait(self.driver, 8).until(
                    EC.presence_of_element_located((By.XPATH,
                        "//*[contains(@class, 'jobs-description') or contains(@class, 'job-details')]"
                    ))
                )
            except TimeoutException:
                pass

            # Try multiple selectors for the job description
            description_selectors = [
                "//div[contains(@class, 'jobs-description__content')]",
                "//div[contains(@class, 'jobs-description')]",
                "//div[contains(@class, 'job-details')]",
                "//article",
                "//*[contains(@class, 'description')]",
            ]

            for selector in description_selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for el in elements:
                        text = el.text.strip()
                        if text and len(text) > 50:
                            logger.debug(f"Job description fetched ({len(text)} chars)")
                            return text[:5000]  # Cap at 5000 chars for LLM
                except Exception:
                    continue

            # Fallback: grab text from the main content area
            try:
                body_text = self.driver.find_element(By.TAG_NAME, 'main').text
                if body_text and len(body_text) > 50:
                    return body_text[:5000]
            except Exception:
                pass

            return ""

        except Exception as e:
            logger.error(f"Error fetching job description: {e}")
            return ""

    def _score_with_llm(self, title: str, company: str, location: str, description: str) -> dict:
        """Use the LLM to score the job against the resume."""
        try:
            prompt = ChatPromptTemplate.from_template(prompts.job_scoring_template)
            chain = prompt | self.llm | StrOutputParser()

            raw_output = chain.invoke({
                "resume": self.resume_text,
                "job_title": title,
                "job_company": company,
                "job_location": location,
                "job_description": description,
                "target_positions": ", ".join(self.positions),
                "preferred_locations": ", ".join(self.locations),
            })

            # Clean and parse JSON from LLM output
            output = raw_output.strip()
            # Try to extract JSON from the response
            json_match = re.search(r'\{[^}]+\}', output, re.DOTALL)
            if json_match:
                score_data = json.loads(json_match.group())
            else:
                score_data = json.loads(output)

            # Validate and clamp scores
            expected_keys = {
                'skills_match': 30,
                'experience_fit': 25,
                'keyword_relevance': 20,
                'growth_potential': 15,
                'location_fit': 10,
            }
            for key, max_val in expected_keys.items():
                if key not in score_data:
                    score_data[key] = 0
                score_data[key] = max(0, min(int(score_data[key]), max_val))

            return score_data

        except Exception as e:
            logger.error(f"LLM scoring failed: {e} {traceback.format_exc()}")
            return {
                'skills_match': 0,
                'experience_fit': 0,
                'keyword_relevance': 0,
                'growth_potential': 0,
                'location_fit': 0,
                'reasoning': f'Scoring failed: {str(e)}'
            }

    def _check_connections(self, company: str) -> tuple:
        """Check if the user has connections at the company on LinkedIn."""
        has_connections = False
        connection_count = 0

        try:
            # Navigate to LinkedIn search for people at this company
            company_search = company.replace(' ', '%20')
            self.driver.get(
                f"https://www.linkedin.com/search/results/people/?keywords={company_search}&network=%5B%22F%22%5D"
            )
            time.sleep(3)

            # Check for connection results
            try:
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.XPATH,
                        "//div[contains(@class, 'search-results')]"
                    ))
                )
            except TimeoutException:
                pass

            # Look for result count
            try:
                result_elements = self.driver.find_elements(By.XPATH,
                    "//div[contains(@class, 'search-results-container')]//span[contains(text(), 'result')]"
                )
                for el in result_elements:
                    text = el.text
                    numbers = re.findall(r'(\d+)', text.replace(',', ''))
                    if numbers:
                        connection_count = int(numbers[0])
                        has_connections = connection_count > 0
                        break
            except Exception:
                pass

            if not has_connections:
                # Fallback: just count the number of people cards shown
                try:
                    people_cards = self.driver.find_elements(By.XPATH,
                        "//div[contains(@class, 'entity-result')]"
                    )
                    connection_count = len(people_cards)
                    has_connections = connection_count > 0
                except Exception:
                    pass

            logger.debug(f"Connections at {company}: {connection_count}")

        except Exception as e:
            logger.debug(f"Connection check failed for {company}: {e}")

        return has_connections, connection_count

    def _print_top_jobs(self):
        """Print a formatted table of the top-scored jobs."""
        top_jobs = self.job_repo.get_jobs_sorted_by_score(limit=15)
        if not top_jobs:
            return

        logger.info("\n" + "=" * 80, color="yellow")
        logger.info("  TOP SCORED JOBS", color="yellow")
        logger.info("=" * 80, color="yellow")
        logger.info(f"{'Score':>5} | {'Conn':>4} | {'Title':<35} | {'Company':<20} | {'Location'}", color="yellow")
        logger.info("-" * 80, color="yellow")

        for job in top_jobs:
            conn_str = f"{job.get('connection_count', 0)}" if job.get('has_connections') else "-"
            title = (job.get('title') or 'Unknown')[:35]
            company = (job.get('company') or 'Unknown')[:20]
            location = (job.get('location') or 'Unknown')[:15]
            logger.info(
                f"{job.get('score', 0):>5} | {conn_str:>4} | {title:<35} | {company:<20} | {location}",
                color="yellow"
            )

        logger.info("=" * 80, color="yellow")
        logger.info(f"Query all results: sqlite3 data_folder/jobs.db \"SELECT title, company, score FROM jobs WHERE score IS NOT NULL ORDER BY score DESC;\"", color="yellow")
