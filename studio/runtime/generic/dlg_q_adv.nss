// tfn-content-studio runtime: dialog action. Param "target" = quest slot K on the speaking object. Moves the PC to that stage.
#include "inc_quest"

void main()
{
    int nTarget = StringToInt(GetScriptParam("target"));

    if (nTarget == 0)
        return;

    AdvanceQuest(OBJECT_SELF, GetPCSpeaker(), nTarget);
}
