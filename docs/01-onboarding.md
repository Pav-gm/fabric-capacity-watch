# Step 1: Onboarding (access and decisions)

Do this before creating anything. Most failed setups come from a missing role, found halfway
through.

## What you need

| You need | Why | How to check | How to get it |
| --- | --- | --- | --- |
| **Capacity admin** on every capacity you want to watch | Fabric only lets capacity admins stream a capacity's events, and keeps checking: if the person who created the stream loses the role, the stream pauses | `python scripts/check_access.py`, or Admin portal > Capacity settings > your capacity > Capacity administrators | A Fabric admin adds you there. For F SKUs the Azure owner of the capacity resource can also add you in the Azure portal (the capacity's "Capacity administrators" setting) |
| **Contributor or higher on a workspace** that runs on a Fabric (F) or Trial capacity | The Eventstream, Eventhouse, dashboard and alert live there | `python scripts/check_access.py --workspace "<name>"` | Create a workspace (needs the "Create workspaces" tenant setting) and assign it to a capacity where you have contributor (Assign) rights, or ask a workspace admin to add you |
| Tenant setting **"Users can create Fabric items"** on for you | Eventstream, Eventhouse, Real-Time Dashboard and Activator are Fabric items | Try creating an Eventhouse in the workspace | A Fabric admin enables it in Admin portal > Tenant settings > Microsoft Fabric (tenant or capacity level) |
| **Room on the capacity that hosts the workspace** | The Eventhouse alone uses about 2 CU whenever it is online, and the stream keeps it online | See the table below | Pick another capacity or scale |
| A supported **region** | Microsoft may not offer Fabric events in every region | Any exceptions are listed at the top of [Explore Fabric capacity operation events](https://learn.microsoft.com/fabric/real-time-hub/explore-fabric-capacity-operation-events) | Host the workspace on a capacity in a supported region |
| On your computer (for Claude Code): **Python 3.10+, Azure CLI, Git**. Docker only to run the tests | The scripts sign in with your Azure CLI login | `python --version`, `az version` | Install them; then `az login` (add `--allow-no-subscriptions` if you have no Azure subscription) |

### Where to host Capacity Watch

The monitoring items cost about 2 to 3 CU around the clock, mostly the Eventhouse. Details in
[07-cost-and-limits.md](07-cost-and-limits.md).

| Hosting capacity | Share of its day | Advice |
| --- | --- | --- |
| F2 | over 100% | Do not use |
| F4 | about 60% | Avoid |
| F8 | about 30% | OK for a dedicated monitoring capacity |
| F16 | about 15% | OK |
| F32 | about 7% | Good |
| F64 | about 4% | Good |
| F128 and up | 2% or less | Good |

Best: a capacity other than the one you watch, so the dashboard still answers when the watched
capacity is rejecting work. Fine: the watched capacity itself, if it is F32 or bigger and you
accept that during interactive rejection your dashboard queries may be rejected too.

## Decisions to make

Claude Code asks you for these and writes them to `setup-notes.md` (not committed):

1. **Capacities to watch.** One Eventstream source per capacity.
2. **Workspace and capacity** that will host Capacity Watch. A new workspace called
   `Capacity Watch` keeps permissions simple. It must not be connected to Git: an Eventstream with
   a capacity events source does not support Git integration or deployment pipelines.
3. **Time zone** for daily totals and local times, as an IANA name such as `America/New_York`
   (default `UTC`).
4. **History to keep.** 30 days by default. Longer is cheap (storage only) and helps with trends.
5. **Who gets alerts:** email addresses, or a Teams chat or channel.
6. **Overview events, yes or no.** Recommended: Fabric's own utilization and throttling numbers
   every 30 seconds, used to verify the rebuilt numbers. Small extra cost.
7. **Who owns the stream long term.** The Eventstream source runs as the person who creates it.
   If that person leaves or stops being capacity admin, events stop (Fabric keeps them for
   24 hours). Create it with an account that will keep the role.

## Privacy

Every operation event carries the identity that ran it (`identity_value`: a user's email or a
service principal ID). Treat the Capacity Watch workspace like any place holding usage logs:
limit who can read the KQL database, keep the retention you actually need, and mention it to
whoever handles data protection in your organization.

## Run the check

```bash
az login                                   # --allow-no-subscriptions if you have no Azure subscription
pip install -r scripts/requirements.txt
python scripts/check_access.py --capacity "<capacity to watch>" --workspace "<workspace to use>"
```

It lists the capacities you are admin on and the workspaces where you can create items, and
ends with "Looks good" or a list of what to fix. It changes nothing.

Done when: every capacity to watch shows `[yes]`, the workspace shows `[yes]`, and the
decisions above are written down.

Next: [02-eventhouse.md](02-eventhouse.md)
