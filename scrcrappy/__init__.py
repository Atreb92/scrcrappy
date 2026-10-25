

import logging

logging.getLogger("scrcrappy").addHandler(logging.NullHandler())  # no log file asked for: no stderr fallback either
