# A server shared by a team

How to set up one Linux server so that several people run SkySqueezer jobs on it, each with their own account,
and write the data straight to a NAS. Two independent parts:

1. **Shared jobs.** Everyone sees the same jobs. When a job's Earth Data Hub key runs out of requests, a colleague
   continues it with their own key, without downloading anything twice.
2. **Output on the NAS.** The NAS share is mounted on the server, so jobs write their Icechunk repository, the Zarr
   export and the temporary chunks directly to it. Nothing passes through the server's own disk.

Both are one-time steps for someone with root on the server. The app needs no other configuration.

## 1. Shared jobs

### Setup (root, once)

```bash
groupadd sksdl                                  # the people who share jobs
usermod -aG sksdl alice; usermod -aG sksdl bob  # each person logs out and in again afterwards

mkdir -p /srv/sks-dl/jobs
chgrp sksdl /srv/sks-dl/jobs
chmod 2775 /srv/sks-dl/jobs                     # group-writable; new folders inherit the group (setgid)

mkdir -p /etc/sks-dl
echo '{"jobs_dir": "/srv/sks-dl/jobs"}' > /etc/sks-dl/config.json
```

Keep the jobs folder on a **local disk** of the server, not on the NAS: jobs use file locks there to make sure
only one worker runs a job, and locks on network filesystems are not reliable.

Each person can also choose a jobs folder in the app (**Jobs → Jobs folder**), which overrides the server-wide
setting for their account; `SKS_DL_JOBS_DIR` overrides both.

### What is shared and what stays private

| Shared (in the jobs folder) | Private (in each person's home) |
|---|---|
| Job definitions, progress, logs | API keys (`~/.config/sks-dl/keys.json`, mode 600) |
| Which account runs a job, who resumed it with which key name | Request counts per key (quota) |
| | Catalogue and sample caches |

API keys are never written to the jobs folder: a job records only the *name* of the key it runs with. When a
colleague resumes it, the job runs under their account with one of their keys.

With a shared jobs folder the app creates files with umask `002`, so the group can write them: job state, the
temporary chunks and the Icechunk repository. The output folder must be group-writable too (for the NAS, see the
mount options below).

### Who to put in the group

Everyone in the group can change every job in the shared folder, so add only people you trust with your
downloads. The app still guards your account against a job file that was tampered with:

- your API key is sent only to Earth Data Hub over HTTPS, whatever dataset URL a job names;
- a job folder containing a symbolic link (e.g. its log pointing at a file of yours) is refused;
- deleting a job's outputs removes only real Zarr or Icechunk stores, never another folder;
- the app's own folders (keys, request counts, caches) are made private (mode 700).

### Continuing a colleague's job

- **Stopped job** (e.g. *Paused at quota limit*): **Resume** asks which of your keys to use. The job continues
  under your account; its requests count on your quota.
- **Running job** (e.g. *Waiting for quota*): **Take over** asks the worker to pause after the unit it is
  processing, then resumes the job with your key. A worker of another account cannot be signalled, so it reads
  the request from the job's `control.json` within a few seconds. Keep the app open until the job has resumed:
  the resume is started by your session.
- **Pause** and **Cancel** work on anyone's job, the same way.

The job card shows who started a job and who runs it.

## 2. Output on the NAS (SMB)

A NAS that offers SMB (e.g. a Synology with its SMB service on) is mounted on the server once. The app
then sees an ordinary folder, e.g. `/mnt/nas/data`, and you choose it (or a folder inside it) as the job's
output directory.

### Setup (root, once)

```bash
apt install cifs-utils                 # Debian/Ubuntu; dnf install cifs-utils on RHEL/Fedora
mkdir -p /mnt/nas/data

# the NAS account the server uses (better a service account than a person's)
cat > /root/.smb-nas <<'EOF'
username=NAS_ACCOUNT
password=NAS_PASSWORD
EOF
chmod 600 /root/.smb-nas
```

Add one line to `/etc/fstab`:

```
//nas.example.org/data  /mnt/nas/data  cifs  credentials=/root/.smb-nas,vers=3.0,uid=root,gid=sksdl,forceuid,forcegid,file_mode=0660,dir_mode=0770,_netdev,x-systemd.automount  0  0
```

Then mount it:

```bash
systemctl daemon-reload
mount /mnt/nas/data
```

What the options do:

- `gid=sksdl`, `file_mode=0660`, `dir_mode=0770`: every member of the group can read and write everything on the
  share. That is what lets a colleague resume a job whose output is on the NAS.
- `vers=3.0`: SMB 3.
- `_netdev,x-systemd.automount`: mounted after the network is up, and again on first use if the NAS was offline.

On the NAS every file shows as created by the mount's NAS account, whoever ran the job.

### Check it

In the app, the check button (✓ list icon) next to the output directory in step 5 tests a folder for real. It creates a tiny
Icechunk repository there, commits it, reads it back and deletes it, then shows the result together with the
free space and the filesystem (`cifs`). The check **writes** a few small files, so only run it on a folder where
that is fine.

### Speed

Temporary chunks go to `<output folder>/tmp/<job>` by default, so with a NAS output folder they go to the NAS too.
When the server has enough local disk, **Download settings → Temporary directory** on a local disk is faster. The
temporary chunks need a few GB (the *Max temporary* setting); the Icechunk repository and the Zarr export stay on
the NAS.
