# -----------------------------------------
# Endroid - XMPP Bot
# Copyright 2012, Ensoft Ltd.
# Created by Jonathan Millican
# -----------------------------------------
import sqlite3
import os.path


# Export constants for system column names
EndroidUniqueID = '_endroid_unique_id'


class TableRow(dict):
    """A regular dict, plus a system 'id' attribute."""
    __slots__ = ()

    def __init__(self, *args, **kwargs):
        super(TableRow, self).__init__(*args, **kwargs)
        if not EndroidUniqueID in self:
            raise ValueError("Cannot create table row from table with no {0} "
                             "column!".format(EndroidUniqueID))

    @property
    def id(self):
        return self[EndroidUniqueID]

class Database(object):
    """
    Wrapper round an sqlite3 Database.

    All accesses are synchronous, TODO use twisted.enterprise.adbapi to 
    asynchronise them.

    """
    connection = None
    cursor = None
    file_name = None
    
    @staticmethod
    def setFile(file_name):
        Database.file_name = os.path.expanduser(file_name)
    
    def __init__(self, modName):
        if Database.connection == None:
            Database.connection = sqlite3.connect(Database.file_name)
            Database.cursor = Database.connection.cursor()
        self.modName = modName
    
    def _tName(self, name):
        return self.modName + "_" + name
    
    @staticmethod
    def _sanitize(inp):
        inp = inp.replace('\\', '\\\\')
        inp = inp.replace('"', '\\"')
        return '"' + inp + '"'
    
    @staticmethod
    def _qMarks(fields, delim=""):
        return ", ".join(delim + "?" + delim for f in fields)
    
    @staticmethod
    def _stringFromFieldNames(fields):
        return ", ".join(Database._sanitize(f) for f in fields)

    @staticmethod
    def _stringFromListItems(list):
        return ", ".join(Database._sanitize(l) for l in list)
    
    @staticmethod
    def _tupleFromFieldValues(fields):
        return tuple(fields.values())
    
    @staticmethod
    def _buildConditions(conditions):
        return " and ".join(Database._sanitize(c) + "=?" for c in conditions) or "1"

    @staticmethod
    def _buildSetConditions(fields):
        return ", ".join(Database._sanitize(c) + "=?" for c in fields)
                    
    def create_table(self, name, fields):
        """
        Create a new table in the database called 'name' and containing fields 
        'fields' (an iterable of strings giving field titles).

        """
        if any(f.startswith('_endroid') for f in fields):
            raise ValueError("An attempt was made to create a table with system-reserved column-name (prefix '_endroid').")
        n = Database._sanitize(self._tName(name))
        fields_string = ', '.join(['{0} INTEGER PRIMARY KEY AUTOINCREMENT'.format(EndroidUniqueID)] + [Database._sanitize(i) for i in fields])
        query = 'CREATE TABLE {0} ({1});'.format(n, fields_string)
        Database.raw(query)
    
    def table_exists(self, name):
        """Check to see if a table called 'name' exists in the database."""
        n = Database._sanitize(self._tName(name))
        query = "SELECT `name` FROM `sqlite_master` WHERE `type`='table' AND `name`={0};".format(n)
        Database.raw(query)
        r = Database.cursor.fetchall()
        count = len(r)
        return count != 0
    
    def insert(self, name, fields):
        """
        Insert a row into table 'name'.
        
        Fields is a dictionary mapping field names (as defined in 
        create_table) to values.

        """
        n = Database._sanitize(self._tName(name))
        query = "INSERT INTO {0} ({1}) VALUES ({2});".format(n,
                               Database._stringFromFieldNames(fields),
                               Database._qMarks(fields, ''))
        tup = Database._tupleFromFieldValues(fields)
        Database.raw(query, tup)
        return Database.cursor.lastrowid
    
    def fetch(self, name, fields, conditions={}):
        """
        Get data from the table 'name'. 

        Returns a list of dictionaries mapping 'fields' to their values, one 
        dictionary for each row which satisfies a condition in conditions.

        Conditions is a dictionary mapping field names to values. A result
        will only be returned from a row if its values match those in conditions.

        E.g.: conditions = {'user' : JoeBloggs} 
        will match only fields in rows which have JoeBloggs in the 'user' field.

        """
        n = Database._sanitize(self._tName(name))
        fields = list(fields) + [EndroidUniqueID]
        query = "SELECT {0} FROM {1} WHERE ({2});".format(
            Database._stringFromListItems(fields), n,
            Database._buildConditions(conditions))
        Database.raw(query, Database._tupleFromFieldValues(conditions))
        c = Database.cursor.fetchall()
        rows = [TableRow(dict(zip(fields, item))) for item in c]
        return rows

    def count(self, name, conditions):
        """Return the number of rows in table 'name' which satisfy conditions."""
        n = Database._sanitize(self._tName(name))
        query = "SELECT COUNT(*) FROM {0} WHERE ({1});".format(n, Database._buildConditions(conditions))
        r = Database.raw(query, Database._tupleFromFieldValues(conditions)).fetchall()
        return r[0][0]

    def delete(self, name, conditions):
        """Delete rows from table 'name' which satisfy conditions."""
        n = Database._sanitize(self._tName(name))
        query = "DELETE FROM {0} WHERE ({1});".format(n, Database._buildConditions(conditions))
        Database.raw(query, Database._tupleFromFieldValues(conditions))
        return Database.cursor.rowcount
    
    def update(self, name, fields, conditions):
        """
        Update rows in table 'name' which satisfy conditions. 

        Fields is a dictionary mapping the field names to their new values.

        """
        n = Database._sanitize(self._tName(name))
        query = "UPDATE {0} SET {1} WHERE ({2});".format(n, Database._buildSetConditions(fields), Database._buildConditions(conditions))
        tup = Database._tupleFromFieldValues(fields)
        tup = tup + Database._tupleFromFieldValues(conditions)
        Database.raw(query, tup)
        return Database.cursor.rowcount

    def empty_table(self, name):
        """Remove all rows from table 'name'."""
        n = Database._sanitize(self._tName(name))
        query = "DELETE FROM {0} WHERE 1;".format(n)
        Database.raw(query)
    
    def delete_table(self, name):
        """Delete table 'name'."""
        n = Database._sanitize(self._tName(name))
        query = "DROP TABLE {0};".format(n)
        Database.raw(query)
    
    @staticmethod
    def raw(command, params=()):
        p = Database.cursor.execute(command, params)
        Database.connection.commit()
        return p
