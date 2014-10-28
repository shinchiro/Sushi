from contextlib import contextmanager
from json import load
import logging
import os
import sys
from common import format_time, SushiError
from demux import Timecodes
from subs import AssScript
import re
from sushi import parse_args_and_run


console_handler = None
root_logger = logging.getLogger('')

tags_stripper = re.compile(r'{.*?}')

def strip_tags(text):
    return tags_stripper.sub(" ", text)


def count_overlaps(events):
    return sum(1 for idx in xrange(1, len(events)) if events[idx].start < events[idx-1].end)


@contextmanager
def set_file_logger(path):
    handler = logging.FileHandler(path, mode='w')
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter('%(message)s'))
    root_logger.addHandler(handler)
    try:
        yield
    finally:
        root_logger.removeHandler(handler)

@contextmanager
def remove_console_logger():
    root_logger.removeHandler(console_handler)
    try:
        yield
    finally:
        root_logger.addHandler(console_handler)

def compare_scripts(ideal_path, test_path, timecodes, test_name, expected_errors):
    ideal = AssScript(ideal_path)
    test = AssScript(test_path)
    if len(test.events) != len(ideal.events):
        logging.critical("Script length didn't match: {0} in ideal vs {1} in test. Test {2}".format(len(ideal.events), len(test.events), test_name))
        return False
    ideal.sort_by_time()
    test.sort_by_time()
    failed = 0
    ft = format_time
    for idx, (i, t) in enumerate(zip(ideal.events, test.events)):
        i_start_frame = timecodes.get_frame_number(i.start)
        i_end_frame = timecodes.get_frame_number(i.end)

        t_start_frame = timecodes.get_frame_number(t.start)
        t_end_frame = timecodes.get_frame_number(t.end)

        if i_start_frame != t_start_frame and i_end_frame != t_end_frame:
            logging.debug(u'{0}: start and end time failed at "{1}". {2}-{3} vs {4}-{5}'.format(idx, strip_tags(i.text), ft(i.start), ft(i.end), ft(t.start), ft(t.end)))
            failed += 1
        elif i_end_frame != t_end_frame:
            logging.debug(u'{0}: end time failed at "{1}". {2} vs {3}'.format(idx, strip_tags(i.text), ft(i.end), ft(t.end)))
            failed += 1
        elif i_start_frame != t_start_frame:
            logging.debug(u'{0}: start time failed at "{1}". {2} vs {3}'.format(idx, strip_tags(i.text), ft(i.start), ft(t.start)))
            failed += 1

    # overlaps_before = count_overlaps(ideal.events)
    # overlaps_after = count_overlaps(test.events)
    # logging.info('Overlaps before: {0}, after: {1}, {2} new overlaps'.format(overlaps_before, overlaps_after, overlaps_after - overlaps_before))
    logging.info('Total lines: {0}, good: {1}, failed: {2}'.format(len(ideal.events), len(ideal.events)-failed, failed))


    if failed > expected_errors:
        logging.critical('Got more failed lines than expected ({0} actual vs {1} expected)'.format(failed, expected_errors))
        return False
    elif failed < expected_errors:
        logging.critical('Got less failed lines than expected ({0} actual vs {1} expected)'.format(failed, expected_errors))
        return False
    else:
        logging.critical('Met expectations')
        return True


def run_test(base_path, plots_path, test_name, params):
    def safe_add_path(args, folder, key, name):
        try:
            args.extend((key, os.path.join(folder, params[name])))
        except KeyError:
            pass

    logging.info('Testing "{0}"'.format(test_name))

    folder = os.path.join(base_path, params['folder'])

    cmd = []

    safe_add_path(cmd, folder, '--src', 'src')
    safe_add_path(cmd, folder, '--dst', 'dst')
    safe_add_path(cmd, folder, '--src-keyframes', 'src-keyframes')
    safe_add_path(cmd, folder, '--dst-keyframes', 'dst-keyframes')
    safe_add_path(cmd, folder, '--src-timecodes', 'src-timecodes')
    safe_add_path(cmd, folder, '--dst-timecodes', 'dst-timecodes')
    safe_add_path(cmd, folder, '--script', 'script')
    safe_add_path(cmd, folder, '--chapters', 'chapters')
    safe_add_path(cmd, folder, '--src-script', 'src-script')
    safe_add_path(cmd, folder, '--dst-script', 'dst-script')
    safe_add_path(cmd, folder, '--max-kf-distance', 'max-kf-distance')
    safe_add_path(cmd, folder, '--max-ts-distance', 'max-ts-distance')
    safe_add_path(cmd, folder, '--max-ts-duration', 'max-ts-duration')

    output_path = os.path.join(folder, params['dst']) + '.sushi.test.ass'
    cmd.extend(('-o', output_path))
    if plots_path:
        cmd.extend(('--test-shift-plot', os.path.join(plots_path, '{0}.png'.format(test_name))))

    with set_file_logger(os.path.join(folder, 'sushi_test.log')):
        logging.debug(' '.join(cmd))
        try:
            with remove_console_logger():
                parse_args_and_run(cmd)
        except Exception as e:
            logging.critical('Sushi failed on test "{0}": {1}'.format(test_name, e.message))
            return False

        ideal_path = os.path.join(folder, params['ideal'])
        try:
            timecodes = Timecodes.from_file(os.path.join(folder, params['dst-timecodes']))
        except KeyError:
            timecodes = Timecodes.cfr(params['fps'])

        return compare_scripts(ideal_path, output_path, timecodes, test_name, params['expected_errors'])


def run():
    root_logger.setLevel(logging.DEBUG)
    global console_handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(message)s'))
    root_logger.addHandler(console_handler)
    failed = ran = 0
    try:
        with open('tests.json') as file:
            json = load(file)
    except IOError as e:
        logging.critical(e)
        sys.exit(2)

    try:
        run_only = json['run-only']
    except KeyError:
        run_only = None

    for test_name in json['tests']:
        if run_only and test_name not in run_only:
            continue
        params = json['tests'][test_name]
        try:
            enabled = not params['disabled']
        except KeyError:
            enabled = True
        if enabled:
            ran += 1
            if not run_test(json['basepath'], json['plots'], test_name, params):
                failed += 1
            logging.info('')
        else:
            logging.warn('Test "{0}" disabled'.format(test_name))
    logging.info('Ran {0} tests, {1} failed'.format(ran, failed))


if __name__ == '__main__':
    run()