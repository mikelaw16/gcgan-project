from usps_to_mnist_base_solver import AbstractSolver
import torch
import torch.optim as optim
import networks
import GANLosses
import itertools
import numpy as np

"""
USPS -> MNIST GcGAN only solver
"""


class Solver(AbstractSolver):
    def __init__(self, config, usps_train_loader, mnist_train_loader):
        super().__init__(config, usps_train_loader, mnist_train_loader)
        self.criterionCycle = GANLosses.CycleLoss()

    def init_models(self):
        """ Models: G_UM, G_MU, D_M, D_U """
        # Networks
        self.G_UM = networks.define_G(input_nc=1, output_nc=1, ngf=self.config.g_conv_dim,
                                      which_model_netG=self.config.which_model_netG, norm='batch', init_type='normal',
                                      gpu_ids=self.gpu_ids)
        self.G_MU = networks.define_G(input_nc=1, output_nc=1, ngf=self.config.g_conv_dim,
                                      which_model_netG=self.config.which_model_netG, norm='batch', init_type='normal',
                                      gpu_ids=self.gpu_ids)
        self.D_M = networks.define_D(input_nc=1, ndf=self.config.d_conv_dim,
                                     which_model_netD=self.config.which_model_netD,
                                     n_layers_D=3, norm='instance', use_sigmoid=True, init_type='normal',
                                     gpu_ids=self.gpu_ids)
        self.D_U = networks.define_D(input_nc=1, ndf=self.config.d_conv_dim,
                                     which_model_netD=self.config.which_model_netD,
                                     n_layers_D=3, norm='instance', use_sigmoid=True, init_type='normal',
                                     gpu_ids=self.gpu_ids)

        # Optimisers
        # single optimiser for both generators
        self.G_optim = optim.Adam(itertools.chain(self.G_UM.parameters(), self.G_MU.parameters()),
                                  self.config.lr, betas=(self.config.beta1, self.config.beta2))
        self.D_M_optim = optim.Adam(self.D_M.parameters(),
                                    lr=self.config.lr, betas=(self.config.beta1, self.config.beta2))
        self.D_U_optim = optim.Adam(self.D_U.parameters(),
                                    lr=self.config.lr, betas=(self.config.beta1, self.config.beta2))
        self.optimizers = [self.G_optim, self.D_M_optim, self.D_U_optim]

        # Schedulers
        self.schedulers = []
        for optimizer in self.optimizers:
            self.schedulers.append(networks.get_scheduler(optimizer, self.config))

    def train(self):
        print('----------- USPS->MNIST: Training model -----------')
        n_iters = self.config.niter + self.config.niter_decay
        iter_count = 0
        # Stats
        loss_D_sum = 0
        loss_G_sum = 0
        d_correct_real = 0  # % of real MNIST the discriminator correctly identifies as real
        d_correct_fake = 0  # % of fake MNIST the discriminator correctly identifies as fake
        correctly_labelled = 0
        usps_processed = 0
        mnist_processed = 0
        while True:
            usps_train_iter = iter(self.usps_train_loader)
            mnist_train_iter = iter(self.mnist_train_loader)
            for usps_batch, mnist_batch in zip(usps_train_iter, mnist_train_iter):
                real_usps, u_labels = usps_batch
                real_mnist, m_labels = mnist_batch
                real_usps = real_usps.cuda()
                real_mnist = real_mnist.cuda()
                usps_processed += len(u_labels)
                mnist_processed += len(m_labels)

                # Generate
                fake_mnist = self.G_UM.forward(real_usps)
                fake_usps = self.G_MU.forward(real_mnist)
                pred_d_m_fake = self.D_M(fake_mnist)
                pred_d_m_real = self.D_M(real_mnist)
                pred_d_u_fake = self.D_U(fake_usps)
                pred_d_u_real = self.D_U(real_usps)

                # Classification accuracy on fake MNIST images
                correctly_labelled += self.get_train_accuracy(fake_mnist, u_labels)

                # Discriminator accuracy on fake & real MNIST
                with torch.no_grad():
                    fake_mnist_guesses = pred_d_m_fake.squeeze().cpu().numpy().round()
                    d_correct_fake += np.sum(fake_mnist_guesses == self.target_fake_label)
                    real_mnist_guesses = pred_d_m_real.squeeze().cpu().numpy().round()
                    d_correct_real += np.sum(real_mnist_guesses == self.target_real_label)

                # Calculate losses and backpropagate
                loss_D_M, loss_D_U = self.backward_D(pred_d_m_fake, pred_d_m_real, pred_d_u_fake, pred_d_u_real)
                loss_D_sum += 0.5 * (loss_D_M + loss_D_U)
                loss_G_sum += self.backward_G(real_usps, real_mnist, fake_usps, fake_mnist, pred_d_m_fake, pred_d_u_fake)

                # update learning rates
                for sched in self.schedulers:
                    sched.step()

                if (iter_count + 1) % 10 == 0:
                    loss_D_avg = loss_D_sum / 10
                    loss_G_avg = loss_G_sum / 10
                    fake_mnist_class_acc = correctly_labelled / usps_processed * 100
                    d_acc_real_mnist = d_correct_real / mnist_processed * 100
                    d_acc_fake_mnist = d_correct_fake / usps_processed * 100
                    self.report_results(iter_count, n_iters, loss_D_avg, loss_G_avg, fake_mnist_class_acc,
                                        d_acc_real_mnist, d_acc_fake_mnist, real_usps, fake_mnist)
                    loss_D_sum, loss_G_sum = 0, 0
                    d_correct_real, d_correct_fake = 0, 0
                    correctly_labelled, usps_processed, mnist_processed = 0, 0, 0

                iter_count += 1
                # if all iterations done, break out of both loops
                if iter_count >= n_iters:
                    break
            if iter_count >= n_iters:
                break

        # DONE
        print('----------- USPS->MNIST: Finished training -----------')

    def backward_D(self, pred_d_m_fake, pred_d_m_real, pred_d_u_fake, pred_d_u_real):
        self.D_M_optim.zero_grad()
        loss_d_m = self.criterionGAN(pred_d_m_fake.cpu(), False) + self.criterionGAN(pred_d_m_real.cpu(), True)
        loss_d_m = loss_d_m.cuda()
        loss_d_m.backward(retain_graph=True)
        self.D_M_optim.step()

        self.D_U_optim.zero_grad()
        loss_d_u = self.criterionGAN(pred_d_u_fake.cpu(), False) + self.criterionGAN(pred_d_u_real.cpu(), True)
        loss_d_u = loss_d_u.cuda()
        loss_d_u.backward(retain_graph=True)
        self.D_U_optim.step()

        return loss_d_m.data.cpu(), loss_d_u.data.cpu()

    def backward_G(self, real_usps, real_mnist, fake_usps, fake_mnist, pred_d_m_fake, pred_d_u_fake):
        self.G_optim.zero_grad()

        # GAN loss
        loss_g_gan = self.criterionGAN(pred_d_m_fake.cpu(), True) * 0.5
        loss_g_gan += self.criterionGAN(pred_d_u_fake.cpu(), True) * 0.5
        loss_g_gan *= self.config.lambda_gan
        loss = loss_g_gan.cuda()

        # Cycle consistency loss
        loss_g_cycle = self.criterionCycle(real_usps, real_mnist, fake_usps, fake_mnist, self.G_UM, self.G_MU)
        loss_g_cycle *= self.config.lambda_cycle
        loss += loss_g_cycle.cuda()

        # Reconstruction loss: CycleGAN version
        if self.config.lambda_reconst > 0:
            loss_g_reconst = 0.5 * self.criterionReconst(self.G_UM(real_mnist), real_mnist)
            loss_g_reconst += 0.5 * self.criterionReconst(self.G_MU(real_usps), real_usps)
            loss_g_reconst *= self.config.lambda_reconst
            loss += loss_g_reconst.cuda()

        # if self.config.lambda_dist > 0:
        #     ####
        #   ... loss_g_dist *= self.config.lambda_dist

        loss.backward()
        self.G_optim.step()

        return loss.data.cpu()
