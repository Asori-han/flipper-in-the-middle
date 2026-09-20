#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/io.h>
#include <linux/jiffies.h>
#include <linux/mii.h>

#define ESW_BASE        0x10110000
#define ESW_SIZE        0x8000

#define ESW_REG_PCR0    0x00c0
#define ESW_REG_PCR1    0x00c4

#define PCR0_DATA_SHIFT 16
#define PCR0_REG_SHIFT  8
#define PCR0_PHY_CMD     BIT(13)
#define PCR1_WT_DONE     BIT(0)

#define PHY_ADDR         1

static void __iomem *esw;

/*
 * Safety switch.
 *
 * Default: apply=0 -> load/unload test only, NO PHY writes.
 * Use apply=1 explicitly to configure PHY1 for 10BASE-T FD autoneg.
 */
static bool apply;
module_param(apply, bool, 0444);
MODULE_PARM_DESC(apply,
                 "Apply 10BASE-T full-duplex-only advertisement to PHY1");

static inline u32 esw_r32(unsigned int reg)
{
    return __raw_readl(esw + reg);
}

static inline void esw_w32(u32 val, unsigned int reg)
{
    __raw_writel(val, esw + reg);
}

/*
 * Replicates rt305x_mii_write() from OpenWrt's esw_rt3050.c.
 */
static int mii_write(u32 phy, u32 reg, u32 data)
{
    unsigned long timeout;

    /*
     * Before issuing a transaction, WT_DONE must be clear.
     */
    timeout = jiffies + 5 * HZ;

    while (esw_r32(ESW_REG_PCR1) & PCR1_WT_DONE) {
        if (time_after(jiffies, timeout)) {
            pr_err("mt7628_phy_lab: timeout waiting WT_DONE=0\n");
            return -ETIMEDOUT;
        }

        cpu_relax();
    }

    data &= 0xffff;

    esw_w32((data << PCR0_DATA_SHIFT) |
            (reg  << PCR0_REG_SHIFT)  |
            phy                       |
            PCR0_PHY_CMD,
            ESW_REG_PCR0);

    /*
     * Transaction completes when WT_DONE becomes set.
     */
    timeout = jiffies + 5 * HZ;

    while (!(esw_r32(ESW_REG_PCR1) & PCR1_WT_DONE)) {
        if (time_after(jiffies, timeout)) {
            pr_err("mt7628_phy_lab: timeout waiting WT_DONE=1\n");
            return -ETIMEDOUT;
        }

        cpu_relax();
    }

    return 0;
}

static int force_10base_t_full(void)
{
    int ret;

    /*
     * Select local PHY register page.
     * This is also what the MT7628 initialization code does.
     */
    ret = mii_write(PHY_ADDR, 31, 0x8000);
    if (ret)
        return ret;

    /*
     * MII Advertisement Register (reg 4):
     *
     * ADVERTISE_CSMA   = IEEE 802.3 selector
     * ADVERTISE_10FULL = advertise 10BASE-T full duplex
     *
     * Deliberately do NOT advertise:
     *   10BASE-T half
     *   100BASE-TX half
     *   100BASE-TX full
     */
    ret = mii_write(PHY_ADDR, MII_ADVERTISE,
                    ADVERTISE_CSMA | ADVERTISE_10FULL);
    if (ret)
        return ret;

    /*
     * Restart autonegotiation.
     *
     * Speed and duplex will be resolved through autonegotiation,
     * so we do not force BMCR_SPEED100 or BMCR_FULLDPLX here.
     */
    ret = mii_write(PHY_ADDR, MII_BMCR,
                    BMCR_ANENABLE | BMCR_ANRESTART);
    if (ret)
        return ret;

    return 0;
}

static int __init mt7628_phy_lab_init(void)
{
    int ret;

    pr_info("mt7628_phy_lab: loading, apply=%d\n", apply);

    esw = ioremap(ESW_BASE, ESW_SIZE);
    if (!esw) {
        pr_err("mt7628_phy_lab: unable to map ESW MMIO\n");
        return -ENOMEM;
    }

    if (!apply) {
        pr_info("mt7628_phy_lab: safety mode; no PHY registers modified\n");
        return 0;
    }

    pr_info("mt7628_phy_lab: configuring PHY%d for 10BASE-T full-duplex-only advertisement\n",
            PHY_ADDR);

    ret = force_10base_t_full();
    if (ret) {
        iounmap(esw);
        esw = NULL;
        return ret;
    }

    pr_info("mt7628_phy_lab: autonegotiation restarted\n");

    return 0;
}

static void __exit mt7628_phy_lab_exit(void)
{
    if (esw)
        iounmap(esw);

    /*
     * Deliberately don't try to restore the PHY here because we cannot
     * safely read/save its previous advertisement with this interface.
     * A router reboot restores the normal driver initialization.
     */
    pr_info("mt7628_phy_lab: unloaded\n");
}

module_init(mt7628_phy_lab_init);
module_exit(mt7628_phy_lab_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("ASIR lab");
MODULE_DESCRIPTION("MT7628 PHY1 10BASE-T laboratory helper");
