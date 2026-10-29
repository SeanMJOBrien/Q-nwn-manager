// tfn-content-studio runtime: quest system for modules that do not ship their own (installed by `nwn-manager studio setup`).
//
// A quest stage is handed out by an object (NPC, creature, item or area) that carries local variables:
//   questK                 = "NN_<journal tag>"   K = slot 1..19, NN = stage number, zero padded
//   questK_prereqM         = "NN_<journal tag>"   optional: stage another quest must have reached
//   questK_jumpstage       = 1                    optional: may be taken from any earlier stage
//   questK_reward_xp_tier / questK_reward_xp_level / questK_reward_gold / questK_reward_item (a resref)
//   questK_pc_script / questK_self_script         optional scripts run when the stage is reached
// Progress lives on the player character as a local integer "qs_<tag>" (saved with the character) and in the journal.
// The function names match The Frozen North's inc_quest so generated dialogs work the same way.

const int HIGHEST_QUEST_COUNT = 20;

// Stage the PC has reached in quest sTag (0 = not started).
int GetQuestEntry(object oPC, string sTag);

// Record that the PC reached stage nStage (never moves backwards) and update the journal.
void SetQuestEntry(object oPC, string sTag, int nStage);

// TRUE if the PC is at or past the stage handed out by slot nTarget of oQuestObject.
int GetIsAtQuestStage(object oQuestObject, object oPC, int nTarget);

// TRUE if the PC is exactly at the stage handed out by slot nTarget of oQuestObject.
int GetIsCurrentlyAtQuestStage(object oQuestObject, object oPC, int nTarget);

// TRUE if the PC may take the stage in slot nTarget now (one stage behind, prerequisites met, not there yet).
int GetIsQuestStageEligible(object oQuestObject, object oPC, int nTarget, int bBluff = FALSE);

// Moves the PC to the stage in slot nTarget if eligible, then runs scripts and gives the rewards.
void AdvanceQuest(object oQuestObject, object oPC, int nTarget, int bBluff = FALSE);

int GetQuestEntry(object oPC, string sTag)
{
    return GetLocalInt(oPC, "qs_" + sTag);
}

void SetQuestEntry(object oPC, string sTag, int nStage)
{
    if (GetQuestEntry(oPC, sTag) >= nStage) return;

    SetLocalInt(oPC, "qs_" + sTag, nStage);
    AddJournalQuestEntry(sTag, nStage, oPC, FALSE, FALSE, TRUE);
}

int GetIsAtQuestStage(object oQuestObject, object oPC, int nTarget)
{
    string sQuest = GetLocalString(oQuestObject, "quest" + IntToString(nTarget));
    int nStage = StringToInt(GetSubString(sQuest, 0, 2));

    if (nStage < 1) return FALSE;

    return GetQuestEntry(oPC, GetSubString(sQuest, 3, 27)) >= nStage;
}

int GetIsCurrentlyAtQuestStage(object oQuestObject, object oPC, int nTarget)
{
    string sQuest = GetLocalString(oQuestObject, "quest" + IntToString(nTarget));
    int nStage = StringToInt(GetSubString(sQuest, 0, 2));

    if (nStage < 1) return FALSE;

    return GetQuestEntry(oPC, GetSubString(sQuest, 3, 27)) == nStage;
}

int GetIsQuestStageEligible(object oQuestObject, object oPC, int nTarget, int bBluff = FALSE)
{
    string sSlot = "quest" + IntToString(nTarget);
    string sQuest = GetLocalString(oQuestObject, sSlot);
    int nStage = StringToInt(GetSubString(sQuest, 0, 2));

    if (nStage < 1) return FALSE;

    int nCurrent = GetQuestEntry(oPC, GetSubString(sQuest, 3, 27));

    if (GetLocalInt(oQuestObject, sSlot + "_jumpstage"))
    {
        if (nStage <= nCurrent) return FALSE;
    }
    else if (!bBluff && nCurrent != nStage - 1) return FALSE;

    int i;
    for (i = 1; i < HIGHEST_QUEST_COUNT; i++)
    {
        string sPrereq = GetLocalString(oQuestObject, sSlot + "_prereq" + IntToString(i));
        int nPrereqStage = StringToInt(GetSubString(sPrereq, 0, 2));

        if (nPrereqStage > 0 && GetQuestEntry(oPC, GetSubString(sPrereq, 3, 27)) < nPrereqStage)
            return FALSE;
    }

    if (GetIsAtQuestStage(oQuestObject, oPC, nTarget)) return FALSE;

    return TRUE;
}

void AdvanceQuest(object oQuestObject, object oPC, int nTarget, int bBluff = FALSE)
{
    if (!GetIsQuestStageEligible(oQuestObject, oPC, nTarget, bBluff)) return;

    string sSlot = "quest" + IntToString(nTarget);
    string sQuest = GetLocalString(oQuestObject, sSlot);

    SetQuestEntry(oPC, GetSubString(sQuest, 3, 27), StringToInt(GetSubString(sQuest, 0, 2)));

    string sScript = GetLocalString(oQuestObject, sSlot + "_pc_script");
    if (sScript != "") ExecuteScript(sScript, oPC);

    sScript = GetLocalString(oQuestObject, sSlot + "_self_script");
    if (sScript != "") ExecuteScript(sScript, oQuestObject);

    // XP: tier 1-4 = 50/100/200/400 base, scaled by the level the quest is meant for (base x level / 5, at least base)
    int nTier = GetLocalInt(oQuestObject, sSlot + "_reward_xp_tier");
    int nLevel = GetLocalInt(oQuestObject, sSlot + "_reward_xp_level");

    if (nTier > 0 && nLevel > 0)
    {
        int nBase = 50;
        if (nTier == 2) nBase = 100;
        else if (nTier == 3) nBase = 200;
        else if (nTier >= 4) nBase = 400;

        int nXP = nBase * nLevel / 5;
        if (nXP < nBase) nXP = nBase;

        GiveXPToCreature(oPC, nXP);
    }

    string sItem = GetLocalString(oQuestObject, sSlot + "_reward_item");
    if (sItem != "") CreateItemOnObject(sItem, oPC, 1);

    int nGold = GetLocalInt(oQuestObject, sSlot + "_reward_gold");
    if (nGold > 0) GiveGoldToCreature(oPC, nGold);
}
