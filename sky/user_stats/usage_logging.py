"""Logging events to Grafana Loki"""

import datetime
import functools
import json
import re
import traceback
from typing import Dict, Union

import requests

from sky import sky_logging
from sky.utils import base_utils
from sky.utils import env_options
from sky.user_stats import utils

logger = sky_logging.init_logger(__name__)

LOG_URL = 'https://178762:eyJrIjoiN2VhYWQ3YWRkNzM0NDY0ZmE4YmRlNzRhYTk2ZGRhOWQ5ZjdkMGE0ZiIsIm4iOiJza3lwaWxvdC11c2VyLXN0YXRzLW1ldHJpY3MiLCJpZCI6NjE1MDQ2fQ=@logs-prod3.grafana.net/api/prom/push'  # pylint: disable=line-too-long
log_timestamp = None

def _make_labels_str(d):
    dict_str = ','.join(f'{k}="{v}"' for k, v in d.items())
    dict_str = '{' + dict_str + '}'
    return dict_str


def _send_message(labels: Dict[str, str], msg):
    if env_options.DISABLE_LOGGING:
        return
    global log_timestamp
    if log_timestamp is None:
        log_timestamp = datetime.datetime.now(datetime.timezone.utc)
        log_timestamp = log_timestamp.isoformat('T')

    labels.update(utils.get_base_labels())
    labels_str = _make_labels_str(labels)

    headers = {'Content-type': 'application/json'}
    payload = {
        'streams': [{
            'labels': labels_str,
            'entries': [{
                'ts': log_timestamp,
                'line': msg
            }]
        }]
    }
    payload = json.dumps(payload)
    response = requests.post(LOG_URL, data=payload, headers=headers)
    if response.status_code != 204:
        logger.debug(f'Grafana Loki failed with response: {response.text}')


def send_cli_cmd():
    """Upload current CLI command to Loki."""
    cmd = base_utils.get_pretty_entry_point()
    labels = {'type': 'cli-cmd'}
    _send_message(labels, cmd)


def _clean_yaml(yaml_info):
    """Remove sensitive information from user YAML."""
    cleaned_yaml_info = []

    redact = False
    redact_type = 'None'
    for line in yaml_info:
        if len(line) > 1 and line[0].strip() == line[0]:
            redact = False
        line_prefix = ''
        if line.startswith('setup:'):
            redact = True
            redact_type = 'SETUP'
            line_prefix = 'setup: '
        if line.startswith('run:'):
            redact = True
            redact_type = 'RUN'
            line_prefix = 'run: '
        if line.startswith('envs: ') and line != 'envs: {}\n':
            redact = True
            redact_type = 'ENVS'
            line_prefix = 'envs: '

        if redact:
            line = f'{line_prefix}REDACTED {redact_type} CODE\n'
        line = re.sub('#.*', '# REDACTED COMMENT', line)
        cleaned_yaml_info.append(line)
    return cleaned_yaml_info


def send_yaml(yaml_config_or_path: Union[Dict, str], yaml_type: str):
    """Upload safe contents of YAML file to Loki."""
    if isinstance(yaml_config_or_path, dict):
        yaml_info = base_utils.dump_yaml_str(yaml_config_or_path).split('\n')
        yaml_info = [info + '\n' for info in yaml_info]
    else:
        with open(yaml_config_or_path, 'r') as f:
            yaml_info = f.readlines()
    yaml_info = _clean_yaml(yaml_info)
    yaml_info = ''.join(yaml_info)
    type_label = yaml_type
    labels = {'type': type_label}
    _send_message(labels, yaml_info)


def send_exception(name: str):

    def _send_exception(func):
        """Decorator to catch exceptions and upload to usage logging."""
        if env_options.DISABLE_LOGGING:
            return func

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except (Exception, SystemExit):
                trace = traceback.format_exc()
                _send_message({'name': name, 'type': 'stack-trace'}, trace)
                raise

        return wrapper

    return _send_exception
