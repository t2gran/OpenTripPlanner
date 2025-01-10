#!/usr/bin/env python3

import os
import re
import subprocess
import sys
import json


# Global constants

POM_FILE_NAME = "pom.xml"
# GitHub label to indicate that a PR needs to be bumped
LBL_BUMP_SER_VER_ID = 'bump serialization id'
SER_VER_ID_PROPERTY = 'otp.serialization.version.id'
SER_VER_ID_PROPERTY_PTN = SER_VER_ID_PROPERTY.replace('.', r'\.')
SER_VER_ID_PATTERN = re.compile('<' + SER_VER_ID_PROPERTY_PTN + r'>\s*(.*)\s*</' + SER_VER_ID_PROPERTY_PTN + '>')

## ------------------------------------------------------------------------------------ ##
##                                  Global Variables                                    ##
## ------------------------------------------------------------------------------------ ##

## Config variables
upstream_remote = None
release_remote = None
release_branch = None
config_branch = None
include_pr_label = None
release_ser_prefix = None

## Options
dry_run = False
debugging = False
hotfix = False
new_ser_ver_id = None

## CLI Arguments
base_revision = None

## Control/computed variables
update_ser_ver_id = False
main_version = None
current_full_version = None
new_full_version = None
pr_to_merge = {}

def main():
    setup_and_verify()

    # Prepare release
    if (not hotfix):
        reset_release_branch_to_base_revision()
        merge_in_labeled_PRs()
        merge_in_config_branch()
        merge_in_old_release_with_no_changes()

    set_maven_pom_version(new_full_version)
    set_ser_ver_id_in_pom_file(new_ser_ver_id)
    commit_new_full_version()
    # run_maven_test()
    tag_release()
    push_release_branch_and_tag()

## ------------------------------------------------------------------------------------ ##
##                                 Top level functions                                  ##
## ------------------------------------------------------------------------------------ ##

def setup_and_verify():
    section("Setting up release process and verifying the environment")
    verify_arguments()
    verify_script_run_from_root()
    verify_git_installed()
    verify_maven_installed()
    load_config()
    verify_base_revision_and_release_branch_exist()
    verify_no_local_git_changes()
    fetch_all_git_remotes()
    resolve_version_number()
    resolve_new_full_version()


    if(not hotfix):
        list_labeled_PRs()
        resolve_new_ser_ver_id()
    print_setup()

def reset_release_branch_to_base_revision():
    section("Reset release branch to base revision ...")
    git_im('checkout', '-B', release_branch, base_revision)

def merge_in_labeled_PRs():
    section("Merge in labeled PRs ...")
    for pr in pr_to_merge:
        # A temp branch is needed here since the PR is in the upstream remote repo
        temp_branch=f'temp-pullrequest-{pr}'
        git('fetch', upstream_remote, f'pull/{pr}/head:{temp_branch}')
        git_im('merge', temp_branch)
        git('branch', '-D', temp_branch)

def merge_in_config_branch():
    if(config_branch == None):
        info('\nNo config branch configured, mering is skipped.')
        return
    section(f"Merge in config branch '{config_branch}' ...")
    git_im('merge', qualified_branch(config_branch))

def commit_new_full_version():
    section("Commit new version with version and serialization version id set ...")
    git_im('commit', '--all', '-m', f'Version {new_full_version} ({new_ser_ver_id})')

def tag_release():
    section(f'Tag release with {new_full_version} ...')
    git_im('tag', '-a', f'v{new_full_version}', '-m', f'Version {new_full_version}')

def push_release_branch_and_tag():
    section("Push new release with pom.xml versions and new tag")
    git_im('push', '-f', f'{release_remote}', f'v{new_full_version}', f'{release_branch}')

# Merge the old version into the new version. This only keep a reference to the old version, the
# resulting git tree of the merge is that of the new branch head, effectively ignoring all changes
# from the old release. This create a continuous line of releases in the release branch.
def merge_in_old_release_with_no_changes():
    section("Merge the old version of into the new version - NO CHANGES COPIED OVER.")
    git_im('merge', '-s', 'ours', qualified_branch(release_branch), '-m', "Merge old release into '{release_branch}' - NO CHANGES COPIED OVER")


## ------------------------------------------------------------------------------------ ##
##                                   Setup and verify                                   ##
## ------------------------------------------------------------------------------------ ##

def verify_script_run_from_root():
    if(sys.argv[0] != "script/custom-release.py"):
        error(f"Run script from root directory.")

def verify_git_installed():
    execute('git', '--version', quiet=False)

def verify_maven_installed():
    execute('mvn', '--version', quiet=False)

def verify_arguments():
    args=[]
    for arg in sys.argv[1:]:
        if(re.match(r'(-h|--help)', arg)):
            help()
        elif(re.match(r'(--dryRun)', arg)):
            global dry_run
            dry_run = True
        elif(re.match(r'(--debug)', arg)):
            global debugging
            debugging = True
        elif(re.match(r'(--hotfix)', arg)):
            global hotfix
            hotfix = True
        elif(re.match(r'(--serVerId)', arg)):
            global new_ser_ver_id
            new_ser_ver_id = True
        else:
            args.append(arg)
    if(len(args) == 0):
        error("No target revision provided.")
    global base_revision
    if(not hotfix):
        base_revision = args[0]

def load_config():
    section("Load configuration...")
    global upstream_remote
    global release_remote
    global release_branch
    global include_pr_label
    global release_ser_prefix
    global config_branch
    with open("script/release_env.json", "r") as f:
        doc = json.load(f)
        upstream_remote = doc['upstream-remote']
        release_remote = doc['release-remote']
        release_branch = doc['release-branch']
        include_pr_label = doc['include-pr-label']
        release_ser_prefix = doc['serialization-prefix']
        config_branch = doc['config-branch']
    if(hotfix):
        base_revision = qualified_branch(release_branch)

    if(len(release_ser_prefix) != 2):
        error(f"Configure the 'serialization-prefix'. The prefix must be exactly two characters long. Value: <{release_ser_prefix}>")


def verify_base_revision_and_release_branch_exist():
    if(hotfix):
        info("Verify base revision and release branch/commit exist ...")
        git('rev-parse', '--quiet', '--verify', base_revision, error="Base revision not found!")
    else:
        info("Verify release branch/commit exist ...")
    git('rev-parse', '--quiet', '--verify', qualified_branch(release_branch), error="Release branch not found!")

def verify_no_local_git_changes():
    info("Verify no local changes exist ...")
    git_im('diff-index', '--quiet', 'HEAD', error="There are local changes!")

# Make sure all remote repos are up-to date
def fetch_all_git_remotes():
    git_im('fetch', '--all', error="Git fetch all remotes failed!")

def resolve_version_number():
    info(f"Resolve version number from base revision ...")
    global main_version
    main_version = read_version_from_pom_file(release_remote)

def resolve_new_full_version():
    info("Resolve new version number ...")
    global new_full_version
    global current_full_version
    p = git('tag', '--list', '--sort=-v:refname', error="Fetch git tags failed!")
    tags = p.stdout.splitlines()

    prefix = f"{main_version}-{release_remote}-"
    pattern = re.compile("v" + prefix.replace('.', r'\.') + r"(\d+)")
    max_tag_version = max(
        (int(m.group(1)) for tag in tags if (m := pattern.match(tag))),
        default=0
    )
    current_full_version = prefix + str(max_tag_version)
    new_full_version = prefix + str(1 + max_tag_version)

def list_labeled_PRs():
    if(not include_pr_label):
        info("The 'include-pr-label' is not set in the release_env.json file. No GitHub PRs are merged.")
        return
    info("Get PRs to include and their labels from GitHub - This requires authentication ...")

    # The query body needs to be on one line, for a unknown reason.
    queryText = 'query ReadOpenPullRequests { ' + \
            'repository(owner:\\"opentripplanner\\", name:\\"OpenTripPlanner\\") ' + \
            '{ pullRequests(first: 100, states: OPEN, labels: \\"' + include_pr_label + '\\") ' + \
            '{ nodes { number, labels(first: 20) { nodes { name } } } } } } }'
    post_body = '''
    {
      "query":"''' + queryText + '''",
      "operationName":"ReadOpenPullRequests"
    }
    '''
    git_hub_access_token=os.environ['GIT_HUB_ACCESS_TOKEN']
    result = execute('curl', '-H', f'Authorization: Bearer {git_hub_access_token}', '-X', 'POST', '-d', post_body, 'https://api.github.com/graphql', errorMsg="GitHub GraphQL Query failed!", quietErr=True)

    # Example response
    #   {"data":{"repository":{"pullRequests":{"nodes":[{"number":2222,"labels":{"nodes":[{"name":"bump serialization id"},{"name":"Entur Test"}]}}]}}}}
    jsonDoc = json.loads(result.stdout)
    for node in jsonDoc['data']['repository']['pullRequests']['nodes']:
        pr_number = node['number']
        pr_labels = []
        labels = node['labels']['nodes']
        ptn = re.compile(f"(?i)({LBL_BUMP_SER_VER_ID}|{include_pr_label})")
        for label in labels:
            lblName = label['name']
            if(ptn.match(lblName)):
                pr_labels.append(lblName)
        pr_to_merge[str(pr_number)] = pr_labels

    global update_ser_ver_id
    update_ser_ver_id = any(LBL_BUMP_SER_VER_ID in labels for labels in pr_to_merge.values())

def resolve_new_ser_ver_id():
    info("Resolve the new serialization version id ...")
    global new_ser_ver_id
    global update_ser_ver_id
    curr_release_hash = git_show_ref(make_git_tag(current_full_version))
    curr_ser_ver_id = read_ser_ver_id_from_pom_file(curr_release_hash)

    # If none of the PRs have the 'bump serialization id' label set, then compare the base revision
    # with the last common ancestor for the base_revision and the release branch. If this revisions
    # are the same, then the serialization version id should be the same.
    if(not update_ser_ver_id):
        info("  - Find ancestor serialization version id ...")
        output = git('log', '-20', '--format=oneline', qualified_branch(release_branch)).stdout
        for line in output.splitlines():
            ancestor_hash = line.split()[0]
            ancestor_ser_ver_id = read_ser_ver_id_from_pom_file(ancestor_hash)
            if(not ancestor_ser_ver_id.startswith(release_ser_prefix)):
                break

        info(f"  - Find base serialization version id ...")
        base_hash = git_show_ref(base_revision)
        base_ser_ver_id = read_ser_ver_id_from_pom_file(base_hash)

        # Update serialization version id in release if serialization version id has changed
        update_ser_ver_id = ancestor_ser_ver_id != base_ser_ver_id
        info(f"  - Ancestor serialization.ver.id is {ancestor_ser_ver_id} and base is {base_ser_ver_id}")

    if(update_ser_ver_id):
        new_ser_ver_id = make_new_ser_ver_id(curr_ser_ver_id)
    else:
        new_ser_ver_id = curr_ser_ver_id

def print_setup():
    section("Configuration")
    info(f"Options")
    info(f"  - Dry run enabled ......... : {dry_run}")
    info(f"  - Debugging enabled ....... : {debugging}")
    info(f"Upstream Git repo")
    info(f"  - Remote name ............. : {upstream_remote}")
    info(f"Base for this release")
    info(f"  - Revision ................ : {base_revision}")
    info(f"Release")
    info(f"  - Remote Git repo ......... : {release_remote}")
    info(f"  - Branch .................. : {qualified_branch(release_branch)}")
    info(f"  - Configuration branch .... : {qualified_branch(config_branch)}")
    info(f"  - Ser.ver.prefix .......... : {release_ser_prefix}")
    info(f"  - Project main version .... : {main_version}")
    info(f"  - Current full version .... : {current_full_version}")
    info(f"  - New full version ........ : {new_full_version}")
    info(f"  - Ser.ver.id incremented .. : {update_ser_ver_id}")
    info(f"  - New ser.ver.id .......... : {new_ser_ver_id}")
    if(include_pr_label):
        info(f"PRs to merge")
    for pr in pr_to_merge:
        info(f"  - {pr} with labels {pr_to_merge[pr]}")


## ------------------------------------------------------------------------------------ ##
##                                   Utility functions                                  ##
## ------------------------------------------------------------------------------------ ##

# Get the full git hash for a qualified full branch name or tag
def git_show_ref(ref):
    if(re.compile(r"[0-9a-f]{40}").match(ref)):
        return ref
    output = execute('git', 'show-ref', ref).stdout
    return output.split()[0]


# Create a tag name used in git for a given version
def make_git_tag(version):
    return f"v{version}"

# Fully qualified  branch name in release remote repo
def qualified_branch(branch):
    return f"{release_remote}/{branch}"

def make_new_ser_ver_id(currentId):
    value = int(currentId[3:])
    v = release_ser_prefix + "-{:04d}".format(value + 1)
    debug(v)
    return v

def read_version_from_pom_file(qualifier_name):
    pom_xml = execute('git', 'show', f"{base_revision}:{POM_FILE_NAME}").stdout
    tokenPtn = re.compile(r'<version>(.*)</version>')
    verPtn = re.compile(r'(\d+\.\d+\.\d+)-(' + qualifier_name + r'-\d+|SNAPSHOT)')

    # Find the first <version>... in the pom_file.
    m = tokenPtn.search(pom_xml)
    if(m):
        print("Version found: " + m.group(1))
        m = verPtn.match(m.group(1).strip())
        if(m):
            print("Main version number: " + m.group(1))
            return m.group(1)
    error(f"Version not found in '{POM_FILE_NAME}'.")

def read_ser_ver_id_from_pom_file(git_hash):
    pom_xml = execute('git', 'show', f"{git_hash}:{POM_FILE_NAME}").stdout
    m = SER_VER_ID_PATTERN.search(pom_xml)
    return m.group(1)

def set_ser_ver_id_in_pom_file(ser_ver_id):
    new_ser_ver_id_property = f'<{SER_VER_ID_PROPERTY}>{new_ser_ver_id}</{SER_VER_ID_PROPERTY}>'
    with open(POM_FILE_NAME, 'r') as input:
        pom_file = input.read()
        pom_file = re.sub(SER_VER_ID_PATTERN, new_ser_ver_id_property, pom_file, 1)
        with open(POM_FILE_NAME, 'w') as output:
            output.write(pom_file)

def set_maven_pom_version(newMavenVersion):
    execute('mvn', 'versions:set', f'-DnewVersion={newMavenVersion}', '-DgenerateBackupPoms=false')

def run_maven_test():
    section('Run tests')
    # Do not use execute here, this takes more than 10 seconds and we want the output to be piped
    subprocess.run(['mvn', 'clean', 'test'])

def git(*cmd, error=''):
    return execute('git', *cmd, errorMsg=error)

# Git impact should be used if the command change or update the system, this command
# is NOT run if the '--dryRun' flag is set.
def git_im(*cmd, error=''):
    return execute('git', *cmd, errorMsg=error, impact=True)

def execute(*cmd, quiet=True, quietErr=False, errorMsg=None, impact=False):
    if(dry_run and impact):
        info(f"=> {cmd}  (--dryRun SKIPPED)")
        return
    debug(f"Run command: {cmd}")
    p = subprocess.run(args=list(cmd), capture_output=True, text=True, timeout=20)
    debug(f"  <= {p.returncode}")

    if(p.stdout and not quiet):
        info(p.stdout)
    if(p.stderr and not quietErr):
        info(p.stderr)
    if(p.returncode != 0):
        if(errorMsg == None):
            error(f"Command {cmd} failed.")
        else:
            error(f"{errorMsg} Command {cmd} failed.")
    return p

## ------------------------------------------------------------------------------------ ##
##                                     Log functions                                    ##
## ------------------------------------------------------------------------------------ ##

def section(msg):
    hr = "-------------------------------------------------------------------------------------------"
    print('')
    print(hr)
    print(f"  {msg}")
    print(hr)

def info(msg):
    print(f"{msg}")

def error(msg):
    print(f"\nERROR {msg}\n")
    sys.stdout.flush()
    exit(1)

def debug(msg):
    if(debugging):
        print(f"DEBUG {msg}")


## ------------------------------------------------------------------------------------ ##
##                                     Help function                                    ##
## ------------------------------------------------------------------------------------ ##

def help():
    section("Help")
    print (f"""
    This script take ONE argument <base-revision>, the base branch or commit to use for the
    release.

    Release process overview
      1. The <release branch> is reset hard to the <base-revision>.
      2. Then the labeled PRs are merged into the release branch. [If <include-pr-label> exist].
      3. The <config branch> is rebased onto the release branch.
      4. The pom.xml file is updated with a new version and a serialization version id.
      5. The release is tested, tagged and pushed to Git repo.

    See the RELEASE_README.md for more details.

    Usage
      script/prepare_release.py [options] <base-revision>

    Arguments
        <base-revision> : The base branch or commit to use for the release. The 'otp/dev-2.x'
                          is the most common base branch to use.

    Options
      -h, --help : Print this help.
      --debug    : Run script with debug output enabled.
      --dryRun   : Run script locally, nothing is pushed to remote server.
      --hotfix   : Create a new release of the <release branch>. Update version(s), tag and push.
      --serVerId : Force incrementation of the serialization version id.

    Examples
      # script/prepare_release.py otp/dev-2.x
      # script/prepare_release.py --dryRun --debug otp/dev-2.x
      # script/prepare_release.py --hotfix --serVerId
    """)
    exit(0)


if __name__ == "__main__":
    main()

