// tfn-content-studio runtime: dialog condition. Param "target" = quest slot K. TRUE if the PC can take that stage now.
#include "inc_quest"

int StartingConditional()
{
    int nTarget = StringToInt(GetScriptParam("target"));

    if (nTarget == 0)
        return FALSE;

    return GetIsQuestStageEligible(OBJECT_SELF, GetPCSpeaker(), nTarget);
}
