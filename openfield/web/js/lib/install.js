// The ways to make your own studio: the commands each one needs, and what a render costs.
//
// The hosted copy knows the repository it was built from; when it does not, the commands carry a plain
// placeholder address, so the sheet still says something a person can act on.

export const COST = "2 to 3 cents per 5-second shot.";

const REPO = "https://github.com/…/openfield-studio"; // the address a hosted copy without site.json cannot name
const FOLDER = "openfield-studio";

/** The folder a clone lands in: the repository URL's last segment, or the default when there is none. */
export function folderName(repoUrl) {
  return String(repoUrl ?? "").split("/").filter(Boolean).pop() || FOLDER;
}

/** The one line that installs the studio on this computer and starts it. */
export function cloneLine(repoUrl) {
  return `git clone ${repoUrl || REPO} && cd ${folderName(repoUrl)} && pip install -e . && openfield serve`;
}

/** The three ways in, each with the commands to run and what it means. */
export function installSteps(repoUrl) {
  const clone = `git clone ${repoUrl || REPO}`;
  return [
    {
      title: "Your own GPU (24-32 GB)",
      text: "Your own card, with the models on it.",
      code: `${clone}\ncd ${folderName(repoUrl)} && pip install -e . && openfield serve`,
    },
    {
      title: "Rent a GPU box",
      text: "One script sets up the box with its models. See docs/CONNECT.md.",
      code: `${clone}\nbash scripts/pod_setup.sh\n# then in the app: Connect a backend`,
    },
    {
      title: "Direct it from your own agent",
      text: "OpenCode, Claude Code or Codex, through the Chat room.",
      code: "openfield serve\n# then open the Chat room",
    },
  ];
}
