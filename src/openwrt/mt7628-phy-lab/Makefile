include $(TOPDIR)/rules.mk

include $(INCLUDE_DIR)/kernel.mk

PKG_NAME:=mt7628-phy-lab
PKG_RELEASE:=1
PKG_BUILD_DIR:=$(KERNEL_BUILD_DIR)/$(PKG_NAME)

include $(INCLUDE_DIR)/package.mk

define KernelPackage/mt7628-phy-lab
  SUBMENU:=Network Devices
  TITLE:=MT7628 PHY laboratory helper
  DEPENDS:=@TARGET_ramips_mt76x8
  FILES:=$(PKG_BUILD_DIR)/mt7628_phy_lab.ko
endef

define KernelPackage/mt7628-phy-lab/description
 Laboratory module that advertises 10BASE-T full duplex on the MT7628 PHY.
 Loading without apply=1 leaves the PHY unchanged.
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)
	$(CP) ./src/* $(PKG_BUILD_DIR)/
endef

define Build/Compile
	$(KERNEL_MAKE) M="$(PKG_BUILD_DIR)" modules
endef

$(eval $(call KernelPackage,mt7628-phy-lab))
