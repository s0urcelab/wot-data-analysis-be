'use strict';

/**
 * @param {Egg.Application} app - egg application
 */
module.exports = app => {
  const { router, controller } = app;

  router.get('/', controller.home.index);
  
  router.get('/storeTanksgg/:ver', controller.home.storeTanksgg);
  router.get('/manual', controller.home.manualGather);
  router.get('/preData', controller.home.preData);
  router.get('/tankList', controller.home.tankList);
  router.get('/history', controller.home.singleTankHistory);
};
