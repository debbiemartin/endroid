# -----------------------------------------
# Endroid - Webex Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------

from endroid.database import Database

from twisted.internet import reactor
from pytz import timezone
import datetime
import cPickle
import logging
import functools

__all__ = (
    'task',
    'Cron',
)


def task(name, persistent=True):
    """
    Decorator for method of Plugin classes that are to be used as callbacks for
    cron tasks.

    This decorator ensures the function is registered with the plugin's cron
    using the given name and persistent arguments. The decorated function can
    be used like a Task (returned from Cron.register):

        >>> CRON_NAME = "MyCronName"
        >>> class Foo(Plugin):
        ...     @task(CRON_NAME)
        ...     def repeat(self, *args): pass
        ...     def message_handler(self, msg):
        ...         self.repeat.setTimeout(10, params)

    That is it provides the setTimeout and doAtTime methods. The decorated
    function can also be called as normal, should that be needed.

    """
    def decorator(fn):
        fn._cron_iscb = True
        fn._cron_name = name
        fn._cron_persistent = persistent
        return fn
    return decorator


class Task(object):
    """
    Wrapper object providing direct access to a specific "task". Obtain an
    instance using register on the Cron singleton.

    Can also be obtained by wrapping a callback method using the @task
    decorator. In either case, the Task object is updated to appear as if it is
    the underlying function, and can be called as if it is.

    """
    def __init__(self, name, cron, fn):
        self.name = name
        self.cron = cron
        self.fn = fn
        # Disguise the Task as the function it is wrapping
        functools.update_wrapper(self, fn)

    def __call__(self, *args, **kwargs):
        return self.fn(*args, **kwargs)

    def doAtTime(self, time, locality, params):
        return self.cron.doAtTime(time, locality, self.name, params)

    def setTimeout(self, timedelta, params):
        return self.cron.setTimeout(timedelta, self.name, params)


class Cron(object):
    # a wrapper around the CronSing singleton
    cron = None

    @staticmethod
    def get():
        if Cron.cron is None:
            Cron.cron = CronSing()
        return Cron.cron


class CronSing(object):
    """
    A singleton providing task scheduling facilities.
    A function may be registered by calling register(function, name) (returning
    a Task object).
    A registered function may be scheduled with either:
        - setTimeout(time, name, params) / doAtTime(time, locality, name, params)
        - or by calling either method on the Task object returned
        by register(), omitting the name parameter.
    Note that params will be pickled for storage in the database.

    When it comes to be called, the function will be called with an argument
    unpickled from params (so even if the function needs no arguments it should
    allow for one eg def foo(_) rather than def foo()).

    """
    def __init__(self):
        self.delayedcall = None
        self.fun_dict = {}
        self.db = Database('Cron')
        # table for tasks which will be called after a certain amount of time
        if not self.db.table_exists('cron_delay'):
            self.db.create_table('cron_delay', 
                                 ['timestamp', 'reg_name', 'params'])
        # table for tasks which will be called at a specific time
        if not self.db.table_exists('cron_datetime'):
            self.db.create_table('cron_datetime', 
                                 ['datetime', 'locality', 'reg_name', 'params'])

    def seconds_until(self, td):
        ds, ss, uss = td.days, td.seconds, td.microseconds
        return float((uss + (ss + ds * 24 * 3600) * 10**6)) / 10**6

    def register(self, function, reg_name, persistent=True):
        """
        Register the callable fun against reg_name.

        Returns a Task object and allows callable to be scheduled with doAtTime
        or setTimeout either on self, or on the Task object returned.

        If persistent is False, any previous reigstrations against reg_name will
        be deleted before the new function is registered.

        """
        # reg_name is the key we use to access the function - we can then set the
        # function to be called using setTimeout or doAtTime with regname = name

        # remove any prior functions with this reg_name
        if not persistent:
            self.removeTask(reg_name)

        self.fun_dict.update({reg_name: function})
        return Task(reg_name, self, function)

    def cancel(self):
        if self.delayedcall:
            self.delayedcall.cancel()
        self.delayedcall = None

    def do_crons(self):
        if self.delayedcall:
            self.delayedcall.cancel()
        self.delayedcall = reactor.callLater(0, self._do_crons)

    def _time_left_delay(self, pickleTime):
        curtime = datetime.datetime.now(timezone('GMT'))
        dt = cPickle.loads(str(pickleTime))
        dt_gmt = dt.astimezone(timezone('GMT'))
        time_delta = dt_gmt - curtime
        return self.seconds_until(time_delta)

    def _time_left_set_time(self, pickleTime, locality):
        curtime = datetime.datetime.now(timezone('GMT'))
        dt = cPickle.loads(str(pickleTime))
        dt_local = timezone(locality).localize(dt)
        dt_gmt = dt_local.astimezone(timezone('GMT'))
        time_delta = dt_gmt - curtime
        return self.seconds_until(time_delta)

    def _do_crons(self):
        self.delayedcall = None
        # retrieve the information about our two kinds of scheduled tasks from
        # the database
        delays = self.db.fetch('cron_delay', 
                               ['timestamp', 'reg_name', 'params', 'rowid'])
        set_times = self.db.fetch('cron_datetime', 
                                  ['datetime', 'reg_name', 'params', 
                                   'locality', 'rowid'])

        # transform the two types of data into a consistant format and combine
        # data is the raw information we retrieved from self.db
        crons_d = [{
            'table':     'cron_delay',
            'data':      data,
            'time_left': self._time_left_delay(data['timestamp'])
        } for data in delays]
        crons_s = [{
            'table':     'cron_datetime',
            'data':      data,
            'time_left': self._time_left_set_time(data['datetime'], 
                                                  data['locality'])
        } for data in set_times]
        crons = crons_d + crons_s

        shortest = None

        # run all crons with time_left <= 0, find smallest time_left amongst
        # others and reschedule ourself to run again after this time
        for cron in crons:
            if cron['time_left'] <= 0:
                # the function is ready to be called
                # remove the entry from the database and call it
                self.db.delete(cron['table'], cron['data'])
                logging.info("Running Cron: {}".format(cron['data']['reg_name']))
                params = cPickle.loads(str(cron['data']['params']))
                try:
                    self.fun_dict[cron['data']['reg_name']](params)
                except KeyError:
                    # If there has been a restart we will have lost our fun_dict
                    # If functions have not been re-registered then we will have a problem.
                    logging.error("Failed to run Cron: {} not in dictionary".format(cron['data']['reg_name']))
            else:
                # update the shortest time left
                if (shortest is None) or cron['time_left'] < shortest:
                    shortest = cron['time_left']
        if not shortest is None:  #ie there is another function to be scheduled
            self.delayedcall = reactor.callLater(shortest, self._do_crons)

    def doAtTime(self, time, locality, reg_name, params):
        """
        Start a cron job to trigger the specified function ('reg_name') with the
        specified arguments ('params') at time ('time', 'locality').

        """
        lTime = timezone(locality).localize(time)
        gTime = lTime.astimezone(timezone('GMT'))

        fmt = "Cron task '{}' set for {} ({} GMT)"
        logging.info(fmt.format(reg_name, lTime, gTime))
        t, p = self._pickleTimeParams(time, params)

        self.db.insert('cron_datetime', {'datetime': t, 'locality': locality, 
                                         'reg_name': reg_name, 'params': p})
        self.do_crons()

    def setTimeout(self, timedelta, reg_name, params):
        """
        Start a cron job to trigger the specified registration ('reg_name') with
        specified arguments ('params') after delay ('timedelta').

        timedelta may either be a datetime.timedelta object, or a real number
        representing a number of seconds to wait. Negative or 0 values will 
        trigger near immediately.

        """
        if not isinstance(timedelta, datetime.timedelta):
            timedelta = datetime.timedelta(seconds=timedelta)

        fmt = 'Cron task "{0}" set to run after {1}'
        logging.info(fmt.format(reg_name, str(timedelta)))

        time = datetime.datetime.now(timezone('GMT')) + timedelta
        t, p = self._pickleTimeParams(time, params)

        self.db.insert('cron_delay', {'timestamp': t, 'reg_name': reg_name,
                                      'params': p})
        self.do_crons()

    def removeTask(self, reg_name):
        """Remove any scheduled tasks registered with reg_name."""
        self.db.delete('cron_delay', {'reg_name': reg_name})
        self.db.delete('cron_datetime', {'reg_name': reg_name})
        self.fun_dict.pop('reg_name', None)

    def getAtTimes(self):
        """
        Return a string showing the registration names of functions scheduled
        with doAtTime and the amount of time they will be called in.

        """
        def get_single_string(data):
            fmt = "  name '{}' to run in '{}:{}:{}'"
            name = data['reg_name']
            delay = int(round(self._time_left_set_time(data['datetime'], data['locality'])))
            return fmt.format(name, delay // 3600, (delay % 3600) // 60, delay % 60)

        data = self.db.fetch('cron_datetime', ['reg_name', 'locality', 'datetime'])
        return "Datetime registrations:\n" + '\n'.join(map(get_single_string, data))

    def getTimeouts(self):
        """
        Return a string showing the registration names of functions scheduled
        with setTimeout and the amount of time they will be called in.

        """
        def get_single_string(data):
            fmt = "  name '{}' to run in '{}:{}:{}'"
            name = data['reg_name']
            delay = int(round(self._time_left_delay(data['timestamp'])))
            return fmt.format(name, delay // 3600, (delay % 3600) // 60, delay % 60)

        data = self.db.fetch('cron_delay', ['reg_name', 'timestamp'])
        return "Timeout registrations:\n" + '\n'.join(map(get_single_string, data))

    def _pickleTimeParams(self, time, params):
        return cPickle.dumps(time), cPickle.dumps(params)
