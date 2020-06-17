import logging
import os

from brightsky.db import get_connection
from brightsky.parsers import get_parser
from brightsky.polling import DWDPoller
from brightsky.utils import dwd_fingerprint


logger = logging.getLogger('brightsky')


def parse(path=None, url=None, export=False):
    if not path and not url:
        raise ValueError('Please provide either path or url')
    parser_cls = get_parser(os.path.basename(path or url))
    parser = parser_cls(path=path, url=url)
    if url:
        parser.download()
        fingerprint = {
            'url': url,
            **dwd_fingerprint(parser.path),
        }
    else:
        fingerprint = None
    records = list(parser.parse())
    parser.cleanup()
    if export:
        exporter = parser.exporter()
        exporter.export(records, fingerprint=fingerprint)
    return records


def poll(enqueue=False):
    updated_files = DWDPoller().poll()
    if enqueue:
        from brightsky.worker import huey, process
        if (expired_locks := huey.expire_locks(1800)):
            logger.warning(
                'Removed expired locks: %s', ', '.join(expired_locks))
        pending_urls = [
            t.args[0] for t in huey.pending() if t.name == 'process']
        enqueued = 0
        for updated_file in updated_files:
            url = updated_file['url']
            if url in pending_urls:
                logger.debug('Skipping "%s": already queued', url)
                continue
            elif huey.is_locked(url):
                logger.debug('Skipping "%s": already running', url)
                continue
            logger.debug('Enqueueing "%s"', url)
            parser_cls = get_parser(os.path.basename(url))
            process(url, priority=parser_cls.PRIORITY)
            enqueued += 1
        logger.info('Enqueued %d updated files for processing', enqueued)
    return updated_files


def clean():
    expiry_intervals = {
        'weather': {
            'forecast': '12 hours',
            'current': '48 hours',
        },
        'synop': {
            'synop': '30 hours',
        },
    }
    parsed_files_expiry_intervals = {
        '%/Z__C_EDZW_%': '1 week',
    }
    logger.info('Deleting expired weather records: %s', expiry_intervals)
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table, table_expires in expiry_intervals.items():
                for observation_type, interval in table_expires.items():
                    cur.execute(
                        f"""
                        DELETE FROM {table} WHERE
                            source_id IN (
                                SELECT id FROM sources
                                WHERE observation_type = %s) AND
                            timestamp < current_timestamp - %s::interval;
                        """,
                        (observation_type, interval),
                    )
                    conn.commit()
                    if cur.rowcount:
                        logger.info(
                            'Deleted %d outdated %s weather records from %s',
                            cur.rowcount, observation_type, table)
            for filename, interval in parsed_files_expiry_intervals.items():
                cur.execute(
                    """
                    DELETE FROM parsed_files WHERE
                        url LIKE %s AND
                        parsed_at < current_timestamp - %s::interval;
                    """,
                    (filename, interval))
                conn.commit()
                if cur.rowcount:
                    logger.info(
                        'Deleted %d outdated parsed file for pattern "%s"',
                        cur.rowcount, filename)
