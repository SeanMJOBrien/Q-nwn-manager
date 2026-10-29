// tfn-content-studio runtime: creature OnDeath. Credits a kill to the killer's party when this creature carries
// `quest_kill = K` (slot K holds the quest stage), then runs the standard death script.
#include "inc_quest"

void main()
{
    int nSlot = GetLocalInt(OBJECT_SELF, "quest_kill");
    object oKiller = GetLastKiller();

    if (nSlot > 0)
    {
        if (GetIsObjectValid(GetMaster(oKiller))) oKiller = GetMaster(oKiller);

        if (GetIsPC(oKiller))
        {
            object oMember = GetFirstFactionMember(oKiller, TRUE);

            while (GetIsObjectValid(oMember))
            {
                if (GetArea(oMember) == GetArea(OBJECT_SELF))
                    AdvanceQuest(OBJECT_SELF, oMember, nSlot);

                oMember = GetNextFactionMember(oKiller, TRUE);
            }
        }
    }

    ExecuteScript("nw_c2_default7", OBJECT_SELF);
}
