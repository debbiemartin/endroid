import logging
from endroid.pluginmanager import Plugin
from twisted.internet.defer import DeferredList


class MUCConfig(object):
    """
    Class to keep well-known config names.
    """

    MEMBERS_ONLY = "muc#roomconfig_membersonly"


class RoomOwner(Plugin):

    def endroid_init(self):
        if self.place != "room":
            return

        def owner_result(is_owner):
            if not is_owner:
                logging.error("EnDroid doesn't appear to be the owner for "
                              "room {}".format(self.place_name))
                return

            logging.debug("EnDroid owns room {}".format(self.place_name))

            # Now get the config to work out what should be done next
            self._get_config()

        # First check if EnDroid owns this room
        d = self.usermanagement.is_room_owner(self.place_name)
        d.addCallback(owner_result)

    def _get_config(self):
        """Get a MUC's config and process it."""

        def process_config(conf_form):
            if conf_form is None:
                # No config items are supported so not much can be done
                pass
            else:
                # A form is a bit like a dictionary
                if MUCConfig.MEMBERS_ONLY in conf_form.keys():
                    # This MUC server supports member only rooms so
                    # update the affiliation list
                    self._update_memberlist()
                else:
                    logging.warning("This MUC server doesn't seem to "
                                    "support member only rooms.")

                # Apply the config
                # @@@Only supported and changed config should be added here
                # Also there might be need for mappings between different config
                # items.
                # configure_room internally sanitises anything it gets
                # allowing only predefined keys and ignoring the rest (so giving it
                # our whole .vars dictionary is safe (and easy))
                self.usermanagement.configure_room(self.place_name, self.vars)            

        d = self.usermanagement.get_configuration(self.place_name)
        d.addCallback(process_config)

    def _get_configured_memberlist(self):
        if 'users' in self.vars:
            memberlist = set(self.vars['users'])
        else:
            # Check for old-style config
            memberlist = self.usermanagement.get_configured_room_memberlist(
                self.place_name)

        return memberlist

    def _update_memberlist(self):
        """Update the member list of this room based on config."""

        def parse_memberlist(results):
            successes, results = zip(*results)

            if not all(successes):
                # One of the calls failed
                logging.error('Failed to get member or owner list for {}'.
                              format(self.place_name))
                return
      
            current_memberlist = set(results[0])
            current_ownerlist = set(results[1])
            conf_memberlist = self._get_configured_memberlist()
                
            logging.debug('Configured memberlist for room {}: {}'.format(
                          self.place_name, ", ".join(conf_memberlist)))
            logging.debug('Current memberlist for room {}: {}'.format(
                          self.place_name, ", ".join(current_memberlist)))
            logging.debug('Current ownerlist for room {}: {}'.format(
                          self.place_name, ", ".join(current_ownerlist)))

            # As another owner we can't perform any affiliation changes to
            # existing owners so remove them from any lists
            new_members = conf_memberlist - current_memberlist - current_ownerlist
            dead_members = current_memberlist - conf_memberlist - current_ownerlist
            if new_members:
                self.usermanagement.room_memberlist_change(
                    self.place_name, new_members)
            if dead_members:
                self.usermanagement.room_memberlist_change(
                    self.place_name, dead_members, remove=True)

        # Get the current memberlist to determine what changes need to be made
        d1 = self.usermanagement.get_room_memberlist(self.place_name)
        d2 = self.usermanagement.get_room_ownerlist(self.place_name)
        DeferredList([d1, d2]).addCallback(parse_memberlist)
