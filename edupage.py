from edupage_api import Edupage
from edupage_api.exceptions import BadCredentialsException, CaptchaException
import dotenv, os

dotenv.load_dotenv()

edupage = Edupage()
username = os.getenv("EDUPAGE_USERNAME")
password = os.getenv("EDUPAGE_PASSWORD")
subdomain = os.getenv("EDUPAGE_SUBDOMAIN")

try:
    edupage.login(username, password, subdomain)
    print("logged in")
except BadCredentialsException:
    print("Wrong username or password!")
except CaptchaException:
    print("Captcha required")

