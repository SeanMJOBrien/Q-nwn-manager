// tfn-content-studio runtime: dialog condition. Param "target" = quest slot K. TRUE if the PC is at or past that stage.
#include "inc_quest"

int StartingConditional()
{
    int nTarget = StringToInt(GetScriptParam("target"));

    if (nTarget == 0)
        return FALSE;

    return GetIsAtQuestStage(OBJECT_SELF, GetPCSpeaker(), nTarget);
}
