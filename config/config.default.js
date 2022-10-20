/* eslint valid-jsdoc: "off" */

'use strict';

/**
 * @param {Egg.EggAppInfo} appInfo app info
 */
module.exports = appInfo => {
  /**
   * built-in config
   * @type {Egg.EggAppConfig}
   **/
  const config = exports = {};

  // use for cookie sign key, should change to your own and keep security
  config.keys = appInfo.name + '_1648893618783_7099';

  // add your middleware config here
  config.middleware = [];

  // add your user config here
  const userConfig = {
    // myAppName: 'egg',
  };

  config.validate = {
    convert: true,
    // validateRoot: false,
  };

  config.security = {
    csrf: {
      enable: false,
    },
    domainWhiteList: ['wot.src.moe'],
  };

  config.multipart = {
    mode: 'file',
    // 单个文件大小
    fileSize: '50mb',
    // 允许上传的最大文件数
    files: 3,
    whitelist: [ '.dds', '.xml' ],
  };

  return {
    ...config,
    ...userConfig,
  };
};
