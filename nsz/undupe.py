from pathlib import Path
from nsz.FileExistingChecks import CreateTargetDict
from nsz.nut import Print
import os
import re
import json
import unicodedata


TITLE_CACHE = json.load(open("titles.json")) if os.path.exists("titles.json") else {}
FILE_NON_ASCII = re.compile(r"[^a-zA-Z0-9@#%&',.\s\-\[\]\(\)\+]")


def strip_accents(s):
	return ''.join(c for c in unicodedata.normalize('NFD', s)
		       if unicodedata.category(c) != 'Mn')


def findTitleById(id):
        shortTitle = id[:-4]
        for obj in TITLE_CACHE.values():
                if "id" in obj and obj["id"] is not None and obj["id"][:-4] == shortTitle:
                        if "name" in obj and obj["name"] is not None:
                                return " ".join(FILE_NON_ASCII.sub("", strip_accents(obj["name"])).split()), obj["region"]
                        else:
                                break
        return "", ""


def isOnWhitelist(args, file):
	if not args.undupe_whitelist == "" and re.match(args.undupe_whitelist, file):
		#if args.undupe_dryrun:
		#	Print.info("[DRYRUN] [WHITELISTED]: " + file)
		#else:
		#	Print.info("[WHITELISTED]: " + file)
		return True
	return False

def undupe(args, argOutFolder):
	filesAtTarget = {}
	alreadyExists = {}
	for f_str in args.file:
		(filesAtTarget, alreadyExists) = CreateTargetDict(Path(f_str).absolute(), args, None, filesAtTarget, alreadyExists)
	Print.info("")

	for (titleID_key, titleID_value) in alreadyExists.items():
		maxVersion = max(titleID_value.keys())
		for (version_key, version_value) in titleID_value.items():

			if args.undupe_old_versions and version_key < maxVersion:
				for file in list(version_value):
					if not isOnWhitelist(args, file):
						if args.undupe_dryrun:
							Print.info("[DRYRUN] [DELETE] [OLD_VERSION]: " + file)
						else:
							os.remove(file)
							Print.info("[DELETED] [OLD_VERSION]: " + file)
				continue


			if not args.undupe_blacklist == "":
				for file in list(version_value):
					if not isOnWhitelist(args, file) and re.match(args.undupe_blacklist, file):
						version_value.remove(file)
						if args.undupe_dryrun:
							Print.info("[DRYRUN] [DELETE] [BLACKLIST]: " + file)
						else:
							os.remove(file)
							Print.info("[DRYRUN] [DELETED] [BLACKLIST]: " + file)

			if not args.undupe_prioritylist == "":
				for file in list(version_value.reverse()):
					if len(version_value) > 1 and not isOnWhitelist(args, file) and re.match(args.undupe_prioritylist, file):
						version_value.remove(file)
						if args.undupe_dryrun:
							Print.info("[DRYRUN] [DELETE] [PRIORITYLIST]: " + file)
						else:
							os.remove(file)
							Print.info("[DRYRUN] [DELETED] [PRIORITYLIST]: " + file)

			firstDeleted = False
			for file in list(version_value[1:]):
				if not isOnWhitelist(args, file):
					if args.undupe_dryrun:
						Print.info("[DRYRUN] [DELETE] [DUPE]: " + file)
						Print.info("Keeping " + version_value[0])
					else:
						os.remove(file)
						Print.info("[DELETED] [DUPE]: " + file)
						Print.info("Keeping " + version_value[0])
				elif not firstDeleted and not isOnWhitelist(args, version_value[0]):
					firstDeleted = True
					if args.undupe_dryrun:
						Print.info("[DRYRUN] [DELETE] [DUPE]: " + version_value[0])
						Print.info("Keeping " + file)
					else:
						os.remove(version_value[0])
						Print.info("[DELETED] [DUPE]: " + version_value[0])
						Print.info("Keeping " + file)
			if args.undupe_rename or args.undupe_hardlink:
				for file in version_value:
					if not isOnWhitelist(args, file):
						title, region = findTitleById(titleID_key)
						if title and region:
							title += " "
							region = "["+region+"]"
						# FIXME get it from control.nacp
						else:
							Print.info("[RENAME] [ERROR_TITLEID_NOT_FOUND] " + file)
							continue
						outFolder = argOutFolder if argOutFolder else Path(file).parent
						newName = str(outFolder.joinpath(title + "["+titleID_key+"]"+region+"[v"+str(version_key)+"]"+Path(file).suffix))
						if args.undupe_hardlink:
							if Path(newName).is_file():
								if Path(file).samefile(Path(newName)):
									Print.debug("[HARDLINK] [SKIPPED] " + newName)
								else:
									Print.info("[HARDLINK] [ERROR_ALREADY_EXIST] " + newName)
							else:
								if args.undupe_dryrun:
									Print.info("[DRYRUN] [HARDLINK]: " + "os.link(" + file + ", " + newName)
								else:
									Print.info("[HARDLINK]: " + "os.link(" + file+  ", " + newName)
									os.link(file, newName)
						if args.undupe_rename:
							if Path(newName).is_file():
								if Path(file).samefile(Path(newName)):
									Print.debug("[RENAME] [SKIPPED] " + newName)
								else:
									Print.info("[RENAME] [ERROR_ALREADY_EXIST] " + newName)
							else:
								if args.undupe_dryrun:
									Print.info("[DRYRUN] [RENAME]: " + "os.rename(" + file + ", " + newName)
								else:
									Print.info("[RENAME]: " + "os.rename(" + file+  ", " + newName)
									os.rename(file, newName)
