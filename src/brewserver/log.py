import logging

# doesnt work
# from fastapi.logger import logger as fastapilogger
# fastapilogger.info("calling the fastapi logge")

## use the built in uvicorn logger without any changes
logger = logging.getLogger("uvicorn")
logger.debug("hi thee")
logger.info("abcdef")
logger.warning("hi thee")

# import json
# import uvicorn
# conf = uvicorn.config.LOGGING_CONFIG
# print(logger.handlers[0].formatter.format)
# print(json.dumps(conf, indent=4))

# TODO this doesn't work on a fresh startup for some reason
# default_handler = [handler for handler in logger.handlers if handler.name == "default"]
# default_handler = default_handler[0]
# default_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
# print(f"got default handler")


## use our own logger
# basic config needs to be called first
logging.basicConfig(
    level=logging.INFO,
    #format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    format="      %(levelname)s   %(filename)s::%(funcName)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# TODO somehow this modifies the uvicorn logger, avoid
# logging.config.dictConfig(conf)
#
# needed to prevent our log entries from showing up twice
logging.getLogger("uvicorn").propagate = False
logger = logging.getLogger("brewserver")
logger.info("done configuring logger")

# from fastapi_cli.utils.cli import CustomFormatter

# formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# handler = logger.handlers[0]
# handler.setFormatter(formatter)
# formatter: CustomFormatter = logger.handlers[0].formatter

# print(formatter.format(""))



conf = """
version: 1
disable_existing_loggers: False

formatters:
  colored:
    # Use Uvicorn's ColourizedFormatter class directly
    class: uvicorn.logging.ColourizedFormatter
    # Define the format string using the 'style' attribute to enable curly brace formatting
    format: "{levelprefix:<8} | {asctime} | {name} | {message}"
    style: "{"
    # Explicitly enable colors
    use_colors: True
  standard:
    format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

handlers:
  console:
    class: logging.StreamHandler
    formatter: colored # Reference the colored formatter
    stream: ext://sys.stdout

loggers:
  "": # root logger
    handlers: [console]
    level: INFO
    propagate: False
  uvicorn.error:
    level: INFO
    handlers: [console]
    propagate: False
  uvicorn.access:
    level: INFO
    handlers: [console]
    propagate: False
"""