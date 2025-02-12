import asyncio
import logging
import os
import sys

import click
import yaml
from dotenv import load_dotenv

from gateway.mqtt import connect_mqtt
from gateway.datapoint import parse_datapoints
from gateway.request import parse_requests
from gateway.core import read, send_periodic, send
from gateway.exceptions import VariableNotFoundError
from gateway.source_handler import CanHandler, CandumpHandler

_mqtt_settings = {}
_can_settings = {}

def get_env_settings_safe(env_name, settings_name, settings, default=None):
    if env_name in os.environ:
        if os.getenv(env_name).lower() in ('true', '1'):
            return True
        elif os.getenv(env_name).lower() in ('false', '0'):
            return False
        else:
            return os.getenv(env_name)
    elif settings_name in settings:
        return settings[settings_name]
    elif default is not None:
        return default
    else:
        raise VariableNotFoundError("Variable not found in env ({}) and settings.yml ({})".format(env_name,
                                                                                                  settings_name))


def parse_mqtt_settings(element):
    try:
        _mqtt_settings["enable"] = get_env_settings_safe("MQTT_ENABLE", "enable", element, default=True)
        _mqtt_settings["name"] = get_env_settings_safe("MQTT_NAME", "name", element)
        _mqtt_settings["topic"] = get_env_settings_safe("MQTT_TOPIC", "topic", element, default="hoval-gw")
        _mqtt_settings["broker"] = get_env_settings_safe("MQTT_BROKER", "broker", element)
        _mqtt_settings["username"] = get_env_settings_safe("MQTT_USERNAME", "username", element)
        _mqtt_settings["password"] = get_env_settings_safe("MQTT_PASSWORD", "password", element)
        _mqtt_settings["port"] = get_env_settings_safe("MQTT_PORT", "port", element, default="1883")
    except VariableNotFoundError as e:
        logging.error(e)

def parse_can_settings(element):
    try:
        _can_settings["interface"] = get_env_settings_safe("CAN_INTERFACE", "interface", element, default="can0")
    except VariableNotFoundError as e:
        logging.error(e)


def parse_settings(settings_file):
    """Parse settings file"""
    settings = yaml.full_load(settings_file)

    for item, element in settings.items():
        if item == "datapoints":
            parse_datapoints(element)
        if item == "requests":
            parse_requests(element)
        if item == "mqtt":
            parse_mqtt_settings(element)
        if item == "can":
            parse_can_settings(element)

@click.command()
@click.option('-v', '--verbose', is_flag=True, help="Debug output")
@click.option('-f', '--file', type=click.Path(resolve_path=True), help="Read can messages from file")
@click.option('-s', '--settings', required=True, type=click.File(), help="Read settings file")
@click.option('-e', '--environment-file', type=click.Path(resolve_path=True), help="Read env file")
def main(verbose, file, settings, environment_file):
    """
    Run main application with can interface
    """
    logging.basicConfig()
    
    # Settings file
    parse_settings(settings)

    # Choose right handler
    if file is None:
        can0 = CanHandler(_can_settings["interface"])
    else:
        can0 = CandumpHandler(file)

    # Verbose output
    if verbose is True:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.INFO)

    # load dotenv
    # todo: parse envs from command line instead of reading env file
    if environment_file:
        load_dotenv(dotenv_path=environment_file, verbose=True if verbose else False)
    else:
        load_dotenv(verbose=True if verbose else False)

    # Setup mqtt
    mqtt_client = None
    if _mqtt_settings["enable"]:
        mqtt_client = connect_mqtt(_mqtt_settings)

    # Start can loop
    loop = asyncio.get_event_loop()
    try:
        asyncio.ensure_future(read(can0, mqtt_client, _mqtt_settings["topic"]))
        if file is None:
            asyncio.ensure_future(send_periodic(can0))
        asyncio.ensure_future(send(can0, mqtt_client, _mqtt_settings["topic"]))
        loop.run_forever()
    except KeyboardInterrupt:
        logging.info("Program exit..")
        pass
    finally:
        mqtt_client.loop_stop()
        can0.close()


if __name__ == "__main__":
    sys.exit(main())
