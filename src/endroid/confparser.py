from ConfigParser import ConfigParser
from ast import literal_eval
from collections import defaultdict
import copy
import re

class Parser(object):
    """Reads an ini-like configuration file into an internal dictionary.
    Extra syntax:
     - nested sections:
        [root:child:grandchild:...]: stored as nested dictionaries with values
        accessible via .get("root", "child", "grandchild", ..., "key")
     - or syntax:
        [root:child1|child2:...]: .get("root", "child1", ...) and .get("root", "child2"...)
        will look in this section. Note that the or syntax is usable at any depth
        and with any number of alternatives (so [root1|root2:child1|child2|child2:...] 
        is fine)
     - wildcard syntax:
        [root:*:grandchild:...]: .get("root", <anything>: "grandchild", ...) will
        look in this section. Again the wildcard character may be used at any depth
        (so [*:*:*:...] is doable)
     - order of search:
        the .get method will return the most specified result it can find. The order
        of search is:
            [foo:bar] - first
            [foo:bar|baz]
            [foo|far:bar]
            [foo|far:bar|baz]
            [foo:*]
            [foo|far:*]
            [*:bar]
            [*:bar|baz]
            [*:*] - last
     - lists:
        - Parser will try to identify lists by the presence interior commas and
        newlines. The entry:
            key = var1, var2, var3
        will be returned as a list
        - For a single item list, a comma must be present:
            key = var1,
        - Multiline lists do not need commas:
            key = var1
                var2
                var3
        as internal newlines are present
     - booleans:
        - literal_eval will convert "True" or "False" to their bool counterparts,
        but "true", "false", "yes", "no" etc will remain as strings.
    Arguments to .get:
      - 'default' may be specified in which case KeyErrors will never be raised
      - 'return_all' will cause get to return all possible results rather than
      only the most relevant
    Notes:
      - All section names will have all whitespace removed and will be converted
      to lower case ([Foo |  BAR ] -> [foo|bar])
      - Values in the config file will be parsed with literal_eval so will return
      from .get as Python objects rather than strings (though if literal_eval fails
      then a string will be returned)
    """
    SPLITTER = re.compile("[,\n]")

    def __init__(self, filename=None):
        self.filename = filename
        self.dict = {}
        self._aliases = defaultdict(list)

        if filename:
            self.load(filename)

    def load(self, filename=None):
        filename = filename or self.filename
        self.read_file(filename)
        self.build_dict()

    def read_file(self, filename):
        cp = ConfigParser()
        cp.optionxform = Parser.sanitise

        with open(filename) as f:
            cp.readfp(f)
            self.filename = filename

        # transform Parser section labels into lists of sanitise label parts
        # eg "foo: bar | Bar2 : BAZ" -> ["foo","bar|bar2","baz"]
        sections = cp.sections()
        process_tuple = Parser.process_tuple
        self._parts = [map(Parser.sanitise, s.split(':')) for s in sections]
        self._items = [map(process_tuple, ts) for ts in map(cp.items, sections)]

    def build_dict(self):
        new_dict = {}
        for part_list, items_list in zip(self._parts, self._items):
            d = new_dict
            for part in part_list:
                d = d.setdefault(part, {})
            # set the value when we get to the last part
            d.update(dict(items_list))

        self.dict = new_dict

        # register aliases (for the or syntax)
        for part in [p for parts in self._parts for p in parts if '|' in p]:
            for sub_p in part.split('|'):
                # register the full arg against its parts if we haven't
                # already so for the arg "name1|name2":
                #   self._aliases[name1] = ["name1|name2"]
                #   self._aliases[name2] = ["name1|name2"]
                if not part in self._aliases[sub_p]:
                    self._aliases[sub_p].append(part)

    def get(self, *args, **kwargs):
        # note that this is quite a slow lookup function to support the wildcard
        # '*' and or '|' syntax without complicating self.dict - shouldn't matter
        # as it shouldn't be called too often
        if not self.filename:
            msg = "[{0}] lookup but no file loaded"
            raise ValueError(msg.format(':'.join(args)))

        dicts = [self.dict]
        for arg in [a.lower() for a in args]:
            # currently looking in [dict1, dict2...] - now move our focus to
            # [dict1[a], dict2[a]... dict1[a|o], dict2[a|o]... dict1[*], dict2[*]...]
            # in order: [arg, aliases (eg arg|other), wildcard] (so most specified
            # comes first)
            dicts = [d.get(key) for d in dicts
                        for key in [arg] + self._aliases[arg] + ['*'] if key in d]
        
        # get the result
        if 'return_all' in kwargs:
            result = dicts
        elif len(dicts):
            result = dicts[0]
        elif 'default' in kwargs:
            result = kwargs['default']
        else:
            msg = "[{0}] not defined in {1}"
            raise KeyError(msg.format(':'.join(args), self.filename))

        # if the result is mutable make a copy of it to prevent accidental modification
        # of the config dictionary
        if isinstance(result, (dict, list)):
            return copy.deepcopy(result)
        else:  # immutable type
            return result


    @staticmethod
    def sanitise(string):
        # remove _all_ whitespace (matched by \s) and convert to lowercase
        return re.sub(r"\s", "", string).lower()

    @staticmethod
    def as_list(string):
        # transforms strings containing interior commas or newlines into a list
        return [s.strip() for s in Parser.SPLITTER.split(string) if s.strip()]

    @staticmethod
    def process_tuple(label_val):
        # given a label, value tuple (where label and value are both strings)
        # attempts to interpret value as a python object using literal_eval
        # and/or as a list (in the case that value contains interior newlines
        # or commas)
        def process_val(value):
            # if literal_eval fails (eg if value really is a string) then return
            # a cleaned-up resion. Note we do not want to apply any other transformation
            # to value as eg case might be important
            try:
                return literal_eval(value)
            except:
                # it is a plain string or cannot be parsed so return as string
                return value.strip()

        label, val = label_val
        # val strings at end of lines will have an \n so must strip them
        val = val.strip()
        if Parser.SPLITTER.search(val):  # val is a list of items
            val = [process_val(v) for v in Parser.as_list(val)]
        else:  # it is single value
            val = process_val(val)

        return (label, val)

