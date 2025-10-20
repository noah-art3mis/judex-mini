import time

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def find_elements_by_class(driver: WebDriver, class_name: str) -> list[WebElement]:
    return driver.find_elements(By.CLASS_NAME, class_name)


def find_element_by_id(
    driver: WebDriver, id: str, initial_delay: float = 0.3, timeout: int = 40
) -> str:
    time.sleep(initial_delay)
    Wait = WebDriverWait(driver, timeout)
    Wait.until(EC.presence_of_element_located((By.ID, id)))
    value = driver.find_element(By.ID, id).get_attribute("value")

    if value is None:
        raise Exception(f"Element with id {id} not found")

    return value


def find_element_by_xpath(
    driver: WebDriver, xpath: str, initial_delay: float = 0.3, timeout: int = 40
) -> str:
    time.sleep(initial_delay)
    Wait = WebDriverWait(driver, timeout)
    Wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    value = driver.find_element(By.XPATH, xpath).get_attribute("innerHTML")

    if value is None:
        raise Exception(f"Element with xpath {xpath} not found")

    return value
