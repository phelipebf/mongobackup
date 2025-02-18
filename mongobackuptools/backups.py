"""
The MIT License (MIT)

Copyright (c) 2015 Zagaran, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

@author: Zags (Benjamin Zagorsky)
@author: Eli Jones
@author: Phil Smith
"""

from datetime import datetime, timedelta
from os import path, remove, listdir
from shutil import rmtree, copy
from mongobackuptools.shell import call, tarbz, untarbz
from mongobackuptools.s3 import s3_upload

DATETIME_FORMAT = "_%Y-%m-%d_%H-%M"


def backup(mongo_username, mongo_password, local_backup_directory_path, host=None, port=None, database=None,
           attached_directory_path=None, custom_prefix="backup",
           mongo_backup_directory_path="/tmp/mongo_dump",
           s3_bucket=None, s3_access_key_id=None, s3_secret_key=None,
           purge_local=None, purge_attached=None, cleanup=True, silent=False):
    """
    Runs a backup operation to At Least a local directory.
    You must provide mongodb credentials along with a a directory for a dump
    operation and a directory to contain your compressed backup.
    
        backup_prefix: optionally provide a prefix to be prepended to your backups,
            by default the prefix is "backup".
        database: optionally provide the name of one specific database to back up
            (instead of backing up all databases on the MongoDB server)
        attached_directory_path: makes a second copy of the backup to a different
            directory.  This directory is checked before other operations and
            will raise an error if it cannot be found.
        s3_bucket: if you have an Amazon Web Services S3 account you can
            automatically upload the backup to an S3 Bucket you provide;
            requires s3_access_key_id and s3_secret key to be passed as well
        s3_access_key_id, s3_secret_key: credentials for your AWS account.
        purge_local: An integer value, the number of days of backups to purge
            from local_backup_directory_path after operations have completed.
        purge_attached: An integer value, the number of days of backups to purge
            from attached_directory_path after operations have completed.
        cleanup: set to False to leave the mongo_backup_directory_path after operations
            have completed.
    """

    if attached_directory_path:
        if not path.exists(attached_directory_path):
            raise Exception(
                "ERROR.  Would have to create %s for your attached storage, make sure that file paths already exist and re-run"
                % (attached_directory_path))

    # Dump mongo, tarbz, copy to attached storage, upload to s3, purge, clean.
    full_file_name_path = local_backup_directory_path + custom_prefix + time_string()
    mongodump(mongo_username, mongo_password, mongo_backup_directory_path, host=host, port=port, database=database, silent=silent)

    local_backup_file = tarbz(mongo_backup_directory_path, full_file_name_path, silent=silent)

    if attached_directory_path:
        copy(local_backup_file, attached_directory_path + local_backup_file.split("/")[-1])

    if s3_bucket:
        s3_upload(local_backup_file, s3_bucket, s3_access_key_id, s3_secret_key)

    if purge_local:
        purge_date = (datetime.utcnow().replace(second=0, microsecond=0) -
                      timedelta(days=purge_local))
        purge_old_files(purge_date, local_backup_directory_path, custom_prefix=custom_prefix)

    if purge_attached and attached_directory_path:
        purge_date = (datetime.utcnow().replace(second=0, microsecond=0) -
                      timedelta(days=purge_attached))
        purge_old_files(purge_date, attached_directory_path, custom_prefix=custom_prefix)

    if cleanup:
        rmtree(mongo_backup_directory_path)


def restore(mongo_user, mongo_password, backup_tbz_path,
            backup_directory_output_path="/tmp/mongo_dump",
            host=None, port=None,
            drop_database=False, cleanup=True, silent=False,
            skip_system_and_user_files=False):
    """
    Runs mongorestore with source data from the provided .tbz backup, using
    the provided username and password.
    The contents of the .tbz will be dumped into the provided backup directory,
    and that folder will be deleted after a successful mongodb restore unless
    cleanup is set to False.
    
    Note: the skip_system_and_user_files is intended for use with the changes
    in user architecture introduced in mongodb version 2.6.
    
    Warning: Setting drop_database to True will drop the ENTIRE
    CURRENTLY RUNNING DATABASE before restoring.
    
    Mongorestore requires a running mongod process, in addition the provided
    user must have restore permissions for the database.  A mongolia superuser
    will have more than adequate permissions, but a regular user may not.
    By default this function will clean up the output of the untar operation.
    """
    if not path.exists(backup_tbz_path):
        raise Exception("the provided tar file %s does not exist." % (backup_tbz_path))

    untarbz(backup_tbz_path, backup_directory_output_path, silent=silent)

    if skip_system_and_user_files:
        system_and_users_path = "%s/admin" % backup_directory_output_path
        if path.exists(system_and_users_path):
            rmtree(system_and_users_path)

    mongorestore(mongo_user, mongo_password, backup_directory_output_path,
                 host=host, port=port,
                 drop_database=drop_database, silent=silent)
    if cleanup:
        rmtree(backup_directory_output_path)


def mongodump(mongo_user, mongo_password, mongo_dump_directory_path, host=None, port=None, database=None, silent=False):
    """ Runs mongodump using the provided credentials on the running mongod
        process.
        
        WARNING: This function will delete the contents of the provided
        directory before it runs. """
    if path.exists(mongo_dump_directory_path):
        # If a backup dump already exists, delete it
        rmtree(mongo_dump_directory_path)
    if silent:
        dump_command = ("mongodump --quiet -u %s -p %s -o %s"
                        % (mongo_user, mongo_password, mongo_dump_directory_path))
    else:
        dump_command = ("mongodump -u %s -p %s -o %s"
                        % (mongo_user, mongo_password, mongo_dump_directory_path))
    if host:
        dump_command += (" --host %s" % host)
    if port:
        dump_command += (" --port %s" % port)
    if database:
        dump_command += (" --db %s" % database)
    call(dump_command, silent=silent)


def mongorestore(mongo_user, mongo_password, backup_directory_path, host=None, port=None, drop_database=False, silent=False):
    """ Warning: Setting drop_database to True will drop the ENTIRE
        CURRENTLY RUNNING DATABASE before restoring.
        
        Mongorestore requires a running mongod process, in addition the provided
        user must have restore permissions for the database.  A mongolia superuser
        will have more than adequate permissions, but a regular user may not.
    """

    if not path.exists(backup_directory_path):
        raise Exception("the provided tar directory %s does not exist."
                        % (backup_directory_path))

    if silent:
        mongorestore_command = ("mongorestore --quiet -u %s -p %s %s"
                                % (mongo_user, mongo_password, backup_directory_path))
    else:
        mongorestore_command = ("mongorestore -v -u %s -p %s %s"
                                % (mongo_user, mongo_password, backup_directory_path))
    if host:
        mongorestore_command += (" --host %s" % host)
    if port:
        mongorestore_command += (" --port %s" % port)
    if drop_database:
        mongorestore_command = mongorestore_command + " --drop"
    call(mongorestore_command, silent=silent)


def time_string():
    """Returns a string with current UTC date and time."""
    return datetime.utcnow().strftime(DATETIME_FORMAT)


def get_backup_file_time_tag(file_name, custom_prefix="backup"):
    """ Returns a datetime object computed from a file name string, with
        formatting based on DATETIME_FORMAT."""
    name_string = file_name[len(custom_prefix):]
    time_tag = name_string.split(".", 1)[0]
    return datetime.strptime(time_tag, DATETIME_FORMAT)


def purge_old_files(date_time, directory_path, custom_prefix="backup"):
    """ Takes a datetime object and a directory path, runs through files in the
        directory and deletes those tagged with a date from before the provided
        datetime.
        If your backups have a custom_prefix that is not the default ("backup"),
        provide it with the "custom_prefix" kwarg. """
    for file_name in listdir(directory_path):
        try:
            file_date_time = get_backup_file_time_tag(file_name, custom_prefix=custom_prefix)
        except ValueError as e:
            if "does not match format" in e.message:
                print("WARNING. file(s) in %s do not match naming convention."
                      % (directory_path))
                continue
            raise e
        if file_date_time < date_time:
            remove(directory_path + file_name)
