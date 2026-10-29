// tfn-content-studio runtime: module OnAcquireItem. A PC picking up an item tagged "quest" advances the stage held in
// the item's own `quest1` variable.
#include "inc_quest"

void main()
{
    object oItem = GetModuleItemAcquired();
    object oPC = GetModuleItemAcquiredBy();

    if (!GetIsPC(oPC) || GetTag(oItem) != "quest") return;

    AdvanceQuest(oItem, oPC, 1);
}
