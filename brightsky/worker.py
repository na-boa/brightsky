import os

from huey import crontab, RedisHuey

from brightsky import tasks


huey = RedisHuey('brightsky', results=False, url=os.getenv('REDIS_URL'))




@huey.task()
def process(url):
    with huey.lock_task(url):
        tasks.parse(url=url, export=True)


@huey.periodic_task(crontab(minute='*/5'))
def poll():
    tasks.poll(enqueue=True)
